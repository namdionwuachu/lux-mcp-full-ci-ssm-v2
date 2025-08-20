from aws_cdk import (
    Stack, Duration, CfnOutput,
    aws_lambda as _lambda,
    aws_apigatewayv2 as apigw2,
    aws_apigatewayv2_integrations as apigw2_integrations,
    aws_iam as iam,
)
from constructs import Construct
from pathlib import Path
import os

class LuxStack(Stack):
    def __init__(self, scope: Construct, cid: str, **kwargs):
        super().__init__(scope, cid, **kwargs)

        policy = iam.PolicyStatement(
            actions=[
                "bedrock:InvokeModel","bedrock:InvokeModelWithResponseStream",
                "secretsmanager:GetSecretValue","ssm:GetParameter"
            ],
            resources=["*"]
        )

        env = {
            "AMADEUS_BASE_URL": os.getenv("AMADEUS_BASE_URL","https://test.api.amadeus.com"),
            "AMADEUS_SECRET_NAME": os.getenv("AMADEUS_SECRET_NAME","/lux/amadeus/credentials"),
            "HOTEL_PROVIDER_ORDER": os.getenv("HOTEL_PROVIDER_ORDER","amadeus"),
            "ALLOWLIST_DOMAINS": os.getenv("ALLOWLIST_DOMAINS",""),
        }

        repo_root = Path(__file__).resolve().parents[1]  # points to <repo_root>

        # Orchestrator
        orchestrator = _lambda.Function(
            self,"Orchestrator",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="handler.lambda_handler",
            timeout=Duration.seconds(20),
            memory_size=512,
            environment=env,
            code=_lambda.Code.from_asset(
                str(repo_root),
                exclude=["cdk","frontend","tests",".git","README.md"],
                bundling=_lambda.BundlingOptions(
                    image=_lambda.Runtime.PYTHON_3_12.bundling_image,
                    command=[
                        "bash","-lc",
                        " && ".join([
                            "mkdir -p /asset-output",
                            # copy orchestrator code to zip root
                            "cp -R lambdas/orchestrator/* /asset-output/",
                            # include shared + tools if your orchestrator imports them
                            "cp -R shared /asset-output/shared || true",
                            "cp -R tools /asset-output/tools || true",
                            # install deps next to code (optional)
                            "if [ -f lambdas/orchestrator/requirements.txt ]; then pip install -r lambdas/orchestrator/requirements.txt -t /asset-output; fi",
                            # force a new asset hash each deploy while iterating
                            "echo $(date +%s) > /asset-output/BUILD_INFO.txt"
                        ])
                    ],
                ),
            ),
        )
        orchestrator.add_to_role_policy(policy)

        # HotelAgent
        hotel_fn = _lambda.Function(
            self,"HotelAgent",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="handler.lambda_handler",
            timeout=Duration.seconds(20),
            memory_size=512,
            environment=env,
            code=_lambda.Code.from_asset(
                str(repo_root),
                exclude=["cdk","frontend","tests",".git","README.md"],
                bundling=_lambda.BundlingOptions(
                    image=_lambda.Runtime.PYTHON_3_12.bundling_image,
                    command=[
                        "bash","-lc",
                        " && ".join([
                            "mkdir -p /asset-output",
                            # copy hotel agent code to zip root
                            "cp -R lambdas/hotel_agent/* /asset-output/",
                            # include shared + tools (REQUIRED here for provider_amadeus)
                            "cp -R shared /asset-output/shared || true",
                            "cp -R tools /asset-output/tools",
                            # install deps next to code
                            "if [ -f lambdas/hotel_agent/requirements.txt ]; then pip install -r lambdas/hotel_agent/requirements.txt -t /asset-output; fi",
                            "echo $(date +%s) > /asset-output/BUILD_INFO.txt"
                        ])
                    ],
                ),
            ),
        )
        hotel_fn.add_to_role_policy(policy)

        # BudgetAgent (likely imports tools.hotels_filter)
        budget_fn = _lambda.Function(
            self,"BudgetAgent",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="handler.lambda_handler",
            timeout=Duration.seconds(20),
            memory_size=512,
            environment=env,
            code=_lambda.Code.from_asset(
                str(repo_root),
                exclude=["cdk","frontend","tests",".git","README.md"],
                bundling=_lambda.BundlingOptions(
                    image=_lambda.Runtime.PYTHON_3_12.bundling_image,
                    command=[
                        "bash","-lc",
                        " && ".join([
                            "mkdir -p /asset-output",
                            "cp -R lambdas/budget_agent/* /asset-output/",
                            "cp -R shared /asset-output/shared || true",
                            "cp -R tools /asset-output/tools",
                            "if [ -f lambdas/budget_agent/requirements.txt ]; then pip install -r lambdas/budget_agent/requirements.txt -t /asset-output; fi",
                            "echo $(date +%s) > /asset-output/BUILD_INFO.txt"
                        ])
                    ],
                ),
            ),
        )
        budget_fn.add_to_role_policy(policy)

        # Wiring (unchanged)
        orchestrator.add_environment("HOTEL_FN", hotel_fn.function_name)
        orchestrator.add_environment("BUDGET_FN", budget_fn.function_name)
        hotel_fn.grant_invoke(orchestrator.role)
        budget_fn.grant_invoke(orchestrator.role)

        http = apigw2.HttpApi(
            self,"LuxApi",
            default_integration=apigw2_integrations.HttpLambdaIntegration("LuxInt", orchestrator)
        )

        CfnOutput(self,"ApiUrl",value=http.api_endpoint,export_name="LuxApiUrl")
