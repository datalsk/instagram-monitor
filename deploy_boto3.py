"""
인스타그램 모니터 배포 스크립트
AWS CLI / SAM CLI 없이 boto3만으로 Lambda + DynamoDB + EventBridge 세팅
"""
import os, sys, json, zipfile, subprocess, tempfile, shutil, time
from pathlib import Path

# ─── .env 로드 ────────────────────────────────────────────────
def load_env():
    for name in (".env", ".env.example"):
        p = Path(__file__).parent / name
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    os.environ.setdefault(k.strip(), v.strip())
            print(f"[env] {name} 로드 완료")
            return
    sys.exit("[오류] .env 파일이 없습니다")

load_env()

import boto3
from botocore.exceptions import ClientError

# ─── 설정 ─────────────────────────────────────────────────────
REGION         = os.environ.get("AWS_REGION", "ap-northeast-2")
TABLE_NAME     = os.environ.get("DYNAMODB_TABLE", "instagram-monitor-state")
FUNCTION_NAME  = "instagram-monitor"
ROLE_NAME      = "instagram-monitor-role"
RULE_NAME      = "instagram-monitor-schedule"
# cron 기반 스케줄 (KST 10:30~11:30, 5분 간격 = UTC 01:30~02:30)
CRON_RULES = [
    ("instagram-monitor-schedule-1", "cron(30,35,40,45,50,55 1 * * ? *)", "KST 10:30~10:55"),
    ("instagram-monitor-schedule-2", "cron(0,5,10,15,20,25,30 2 * * ? *)",  "KST 11:00~11:30"),
]

ENV_VARS = {
    "DYNAMODB_TABLE":       TABLE_NAME,
    "INSTAGRAM_ACCOUNTS":   os.environ.get("INSTAGRAM_ACCOUNTS", "family_koreanfood"),
    "OPENAI_API_KEY":       os.environ["OPENAI_API_KEY"],
    "SLACK_BOT_TOKEN":      os.environ["SLACK_BOT_TOKEN"],
    "SLACK_USER_IDS":       os.environ.get("SLACK_USER_IDS", ""),
    "OPENAI_MODEL":         os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
}

boto_kwargs = dict(
    region_name=REGION,
    aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
)

def step(n, msg):
    print(f"\n[{n}] {msg}")

def ok(msg):  print(f"    [OK] {msg}")
def info(msg): print(f"    >> {msg}")

# ─── Step 1: DynamoDB 테이블 ───────────────────────────────────
step(1, "DynamoDB 테이블 생성")
ddb = boto3.client("dynamodb", **boto_kwargs)
try:
    ddb.create_table(
        TableName=TABLE_NAME,
        BillingMode="PAY_PER_REQUEST",
        AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}],
        KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}],
    )
    # 테이블 ACTIVE 상태까지 대기
    info("테이블 생성 대기 중...")
    waiter = ddb.get_waiter("table_exists")
    waiter.wait(TableName=TABLE_NAME, WaiterConfig={"Delay": 3, "MaxAttempts": 20})
    ddb.update_time_to_live(
        TableName=TABLE_NAME,
        TimeToLiveSpecification={"Enabled": True, "AttributeName": "ttl"},
    )
    ok(f"{TABLE_NAME} 생성 완료")
except ClientError as e:
    if "ResourceInUseException" in str(e):
        ok(f"{TABLE_NAME} 이미 존재 (건너뜀)")
    else:
        sys.exit(f"[오류] DynamoDB: {e}")

# ─── Step 2: IAM 역할 ──────────────────────────────────────────
step(2, "IAM 역할 생성")
iam = boto3.client("iam", **boto_kwargs)

trust = json.dumps({
    "Version": "2012-10-17",
    "Statement": [{
        "Effect": "Allow",
        "Principal": {"Service": "lambda.amazonaws.com"},
        "Action": "sts:AssumeRole",
    }],
})

try:
    role = iam.create_role(RoleName=ROLE_NAME, AssumeRolePolicyDocument=trust)
    role_arn = role["Role"]["Arn"]
    ok(f"역할 생성: {role_arn}")

    iam.attach_role_policy(
        RoleName=ROLE_NAME,
        PolicyArn="arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole",
    )
    # DynamoDB 인라인 정책
    account_id = boto3.client("sts", **boto_kwargs).get_caller_identity()["Account"]
    iam.put_role_policy(
        RoleName=ROLE_NAME,
        PolicyName="DynamoDBAccess",
        PolicyDocument=json.dumps({
            "Version": "2012-10-17",
            "Statement": [{
                "Effect": "Allow",
                "Action": ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:Query"],
                "Resource": f"arn:aws:dynamodb:{REGION}:{account_id}:table/{TABLE_NAME}",
            }],
        }),
    )
    ok("정책 연결 완료 (30초 대기 중...)")
    time.sleep(30)  # IAM 전파 대기

except ClientError as e:
    if "EntityAlreadyExists" in str(e):
        role_arn = iam.get_role(RoleName=ROLE_NAME)["Role"]["Arn"]
        ok(f"역할 이미 존재: {role_arn}")
    else:
        sys.exit(f"[오류] IAM (권한 부족 가능): {e}")

# ─── Step 3: Lambda 패키지 빌드 ───────────────────────────────
step(3, "Lambda 패키지 빌드 (pip install 중...)")
build_dir = Path(tempfile.mkdtemp())
src_dir   = Path(__file__).parent

# RSS 방식으로 전환 — instaloader 불필요, anthropic만 설치
subprocess.run(
    [sys.executable, "-m", "pip", "install", "openai>=1.0.0",
     "--platform", "manylinux2014_x86_64",
     "--implementation", "cp", "--python-version", "3.11",
     "--only-binary=:all:", "-t", str(build_dir), "--quiet"],
    check=True,
)
ok("의존성 설치 완료")

# 소스 파일 복사
for f in ["lambda_function.py", "instagram_fetcher.py",
          "summarizer.py", "storage.py", "slack_notifier.py"]:
    shutil.copy(src_dir / f, build_dir / f)
ok("소스 파일 복사 완료")

# zip 생성
zip_path = src_dir / "lambda_package.zip"
with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
    for file in build_dir.rglob("*"):
        if file.is_file():
            zf.write(file, file.relative_to(build_dir))
shutil.rmtree(build_dir)
size_mb = zip_path.stat().st_size / 1024 / 1024
ok(f"패키지 생성: lambda_package.zip ({size_mb:.1f} MB)")

# ─── Step 4: Lambda 함수 생성/업데이트 ────────────────────────
step(4, "Lambda 함수 배포")
lam = boto3.client("lambda", **boto_kwargs)
zip_bytes = zip_path.read_bytes()

try:
    lam.create_function(
        FunctionName=FUNCTION_NAME,
        Runtime="python3.11",
        Role=role_arn,
        Handler="lambda_function.lambda_handler",
        Code={"ZipFile": zip_bytes},
        Timeout=120,
        MemorySize=256,
        Environment={"Variables": ENV_VARS},
    )
    ok(f"{FUNCTION_NAME} 생성 완료")
except ClientError as e:
    if "ResourceConflictException" in str(e) or "Function already exist" in str(e):
        info("이미 존재 - 코드 업데이트 중...")
        lam.update_function_code(FunctionName=FUNCTION_NAME, ZipFile=zip_bytes)
        # 코드 업데이트 완료 대기
        waiter = lam.get_waiter("function_updated")
        waiter.wait(FunctionName=FUNCTION_NAME, WaiterConfig={"Delay": 3, "MaxAttempts": 20})
        lam.update_function_configuration(
            FunctionName=FUNCTION_NAME,
            Environment={"Variables": ENV_VARS},
        )
        ok(f"{FUNCTION_NAME} 업데이트 완료")
    else:
        sys.exit(f"[오류] Lambda: {e}")

# 함수 ARN 조회
func_arn = lam.get_function(FunctionName=FUNCTION_NAME)["Configuration"]["FunctionArn"]
info(f"ARN: {func_arn}")

# ─── Step 5: EventBridge 스케줄 ───────────────────────────────
step(5, "EventBridge cron 스케줄 등록 (KST 10:30~11:30, 5분 간격)")
events = boto3.client("events", **boto_kwargs)

# 기존 rate 기반 규칙 제거
for old_rule in ["instagram-monitor-schedule"]:
    try:
        events.remove_targets(Rule=old_rule, Ids=["lambda"])
        events.delete_rule(Name=old_rule)
        ok(f"기존 규칙 삭제: {old_rule}")
    except ClientError:
        pass

for rule_name, cron_expr, label in CRON_RULES:
    rule_arn = events.put_rule(
        Name=rule_name,
        ScheduleExpression=cron_expr,
        State="ENABLED",
        Description=f"Instagram polling {label}",
    )["RuleArn"]
    ok(f"규칙 생성: {rule_name} ({label})")

    events.put_targets(
        Rule=rule_name,
        Targets=[{"Id": "lambda", "Arn": func_arn}],
    )

    try:
        lam.add_permission(
            FunctionName=FUNCTION_NAME,
            StatementId=f"EventBridgeInvoke-{rule_name}",
            Action="lambda:InvokeFunction",
            Principal="events.amazonaws.com",
            SourceArn=rule_arn,
        )
    except ClientError as e:
        if "ResourceConflictException" not in str(e):
            raise
ok("Lambda 타겟 및 권한 연결 완료")

# ─── 완료 ─────────────────────────────────────────────────────
print("\n" + "="*50)
print("  [완료] 배포 성공!")
print("="*50)
print(f"  Lambda   : {FUNCTION_NAME}")
print(f"  DynamoDB : {TABLE_NAME}")
print(f"  스케줄   : KST 10:30~11:30, 5분 간격 (하루 13회)")
print(f"  계정     : {ENV_VARS['INSTAGRAM_ACCOUNTS']}")
print(f"  Slack    : webhook")
print()
print("  새 게시물 감지 시 Slack DM이 자동 전송됩니다.")
print("  CloudWatch Logs에서 실행 로그를 확인할 수 있습니다.")
print("="*50)
