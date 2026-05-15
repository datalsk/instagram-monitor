"""
Lambda 배포 스크립트 — 코드 업데이트 + EventBridge 활성화
기존 인프라(Lambda 함수, DynamoDB, IAM) 그대로 활용
"""
import os, sys, zipfile, subprocess, tempfile, shutil
from pathlib import Path


def load_env():
    p = Path(__file__).parent / ".env"
    if not p.exists():
        sys.exit("[오류] .env 파일이 없습니다")
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())


load_env()
import boto3
from botocore.exceptions import ClientError

REGION        = os.environ.get("AWS_REGION", "ap-northeast-2")
FUNCTION_NAME = "instagram-monitor"
CRON_RULES = [
    ("instagram-monitor-schedule-2", "cron(0,5,10,15,20,25,30 2 * * ? *)", "KST 11:00~11:30"),
]
RULES_TO_DELETE = ["instagram-monitor-schedule-1"]
ENV_VARS = {
    "DYNAMODB_TABLE":     os.environ.get("DYNAMODB_TABLE", "instagram-monitor-state"),
    "INSTAGRAM_ACCOUNTS": os.environ.get("INSTAGRAM_ACCOUNTS", "family_koreanfood"),
    "OPENAI_API_KEY":     os.environ["OPENAI_API_KEY"],
    "SLACK_BOT_TOKEN":    os.environ["SLACK_BOT_TOKEN"],
    "SLACK_USER_IDS":     os.environ.get("SLACK_USER_IDS", ""),
    "OPENAI_MODEL":       os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
    # AWS_REGION / AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY 는 Lambda 예약 변수라 설정 불가
    # Lambda 실행 역할(IAM)이 DynamoDB 권한을 갖고 있으면 boto3가 자동으로 자격증명 사용
}
boto_kwargs = dict(
    region_name=REGION,
    aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
)
src_dir = Path(__file__).parent


# ── Step 1: 패키지 빌드 ───────────────────────────────────────────
print("[1] 패키지 빌드 중...")
build_dir = Path(tempfile.mkdtemp())

subprocess.run([
    sys.executable, "-m", "pip", "install",
    "curl_cffi>=0.7.0", "openai>=1.0.0",
    "--platform", "manylinux2014_x86_64",
    "--implementation", "cp", "--python-version", "3.11",
    "--only-binary=:all:", "-t", str(build_dir), "--quiet",
], check=True)

for f in ["lambda_function.py", "instagram_fetcher.py",
          "summarizer.py", "storage.py", "slack_notifier.py"]:
    shutil.copy(src_dir / f, build_dir / f)

zip_path = src_dir / "lambda_package.zip"
with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
    for file in build_dir.rglob("*"):
        if file.is_file():
            zf.write(file, file.relative_to(build_dir))
shutil.rmtree(build_dir)
print(f"  lambda_package.zip ({zip_path.stat().st_size / 1024 / 1024:.1f} MB)")


# ── Step 2: Lambda 코드 업데이트 ─────────────────────────────────
print("\n[2] Lambda 코드 업데이트 중...")
lam = boto3.client("lambda", **boto_kwargs)

lam.update_function_code(FunctionName=FUNCTION_NAME, ZipFile=zip_path.read_bytes())
lam.get_waiter("function_updated").wait(FunctionName=FUNCTION_NAME)
lam.update_function_configuration(
    FunctionName=FUNCTION_NAME,
    Environment={"Variables": ENV_VARS},
    Timeout=120,
    MemorySize=256,
)
lam.get_waiter("function_updated").wait(FunctionName=FUNCTION_NAME)

func_arn = lam.get_function(FunctionName=FUNCTION_NAME)["Configuration"]["FunctionArn"]
zip_path.unlink()
print(f"  완료: {func_arn}")


# ── Step 3: EventBridge cron 규칙 활성화 ─────────────────────────
print("\n[3] EventBridge 규칙 활성화 중...")
events = boto3.client("events", **boto_kwargs)

for old_rule in RULES_TO_DELETE:
    try:
        events.remove_targets(Rule=old_rule, Ids=["lambda"])
    except ClientError:
        pass
    try:
        events.delete_rule(Name=old_rule)
        print(f"  삭제: {old_rule}")
    except ClientError:
        pass

for rule_name, cron_expr, label in CRON_RULES:
    events.put_rule(
        Name=rule_name,
        ScheduleExpression=cron_expr,
        State="ENABLED",
        Description=f"Instagram polling {label}",
    )
    events.put_targets(Rule=rule_name, Targets=[{"Id": "lambda", "Arn": func_arn}])

    try:
        rule_arn = events.describe_rule(Name=rule_name)["Arn"]
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

    print(f"  활성화: {rule_name} ({label})")


print("\n✅ 배포 완료!")
print(f"  Lambda   : {FUNCTION_NAME}")
print(f"  스케줄   : KST 11:00~11:30, 5분 간격")
print(f"  계정     : {ENV_VARS['INSTAGRAM_ACCOUNTS']}")
