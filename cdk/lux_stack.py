from aws_cdk import (
    Stack, Duration, CfnOutput, BundlingOptions,
    aws_lambda as _lambda,
    aws_apigatewayv2 as apigw2,
    aws_apigatewayv2_integrations as apigw2_integrations,
    aws_iam as iam,
)
from aws_cdk import aws_secretsmanager as secrets
from constructs import Construct
from pathlib import Path
import os


class LuxStack(Stack):
    def __init__(self, scope: Construct, cid: str, **kwargs):
        super().__init__(scope, cid, **kwargs)

        # ---- Least-privilege policy (NO Secrets Manager here)
        bedrock_ssm = iam.PolicyStatement(
            actions=[
                "bedrock:InvokeModel",
                "bedrock:InvokeModelWithResponseStream",
                "ssm:GetParameter",
            ],
            resources=["*"],
        )

        # ---- Common environment for all Lambdas
        env = {
            "AMADEUS_BASE_URL": os.getenv("AMADEUS_BASE_URL", "https://test.api.amadeus.com"),
            "AMADEUS_SECRET_NAME": os.getenv("AMADEUS_SECRET_NAME", "/lux/amadeus/credentials"),
            "HOTEL_PROVIDER_ORDER": os.getenv("HOTEL_PROVIDER_ORDER", "amadeus"),
            "ALLOWLIST_DOMAINS": os.getenv("ALLOWLIST_DOMAINS", ""),
            # Planner option: include responder_narrate as the last step
            "INCLUDE_RESPONDER": os.getenv("INCLUDE_RESPONDER", "true"),

            # Amadeus provider knobs
            "AMADEUS_MAX_HOTELS": os.getenv("AMADEUS_MAX_HOTELS", "60"),
            "AMADEUS_TARGET_RESULTS": os.getenv("AMADEUS_TARGET_RESULTS", "30"),
            "AMADEUS_TIME_BUDGET_SEC": os.getenv("AMADEUS_TIME_BUDGET_SEC", "17"),
            "AMADEUS_OFFERS_CHUNK_SIZE": os.getenv("AMADEUS_OFFERS_CHUNK_SIZE", "12"), # lowered from 20 → 12
            "AMADEUS_INTER_CHUNK_SLEEP": os.getenv("AMADEUS_INTER_CHUNK_SLEEP", "0.15"),
            "AMADEUS_MAX_RETRIES": os.getenv("AMADEUS_MAX_RETRIES", "5"),
            "AMADEUS_BASE_BACKOFF": os.getenv("AMADEUS_BASE_BACKOFF", "1.0"),

            # Google Places (consistent pattern: pass secret NAME, not key)
            "GOOGLE_PLACES_SECRET_NAME": os.getenv("GOOGLE_PLACES_SECRET_NAME", "/lux/google/places_api_key"),
            "ENABLE_PLACES_PHOTOS": os.getenv("ENABLE_PLACES_PHOTOS", "1"),
            "MAX_PHOTOS_PER_HOTEL": os.getenv("MAX_PHOTOS_PER_HOTEL", "4"),
        }

        repo_root = Path(__file__).resolve().parents[1]  # <repo_root>

        # ---- Orchestrator
        orchestrator = _lambda.Function(
            self, "Orchestrator",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="handler.lambda_handler",
            timeout=Duration.seconds(20),
            memory_size=512,
            environment=env,
            code=_lambda.Code.from_asset(
                str(repo_root),
                exclude=["cdk", "frontend", "tests", ".git", "README.md"],
                bundling=BundlingOptions(
                    image=_lambda.Runtime.PYTHON_3_12.bundling_image,
                    command=[
                        "bash", "-lc",
                        " && ".join([
                            "mkdir -p /asset-output",
                            "cp -R lambdas/orchestrator/* /asset-output/",
                            "cp -R shared /asset-output/shared || true",
                            "cp -R tools /asset-output/tools || true",
                            "if [ -f lambdas/orchestrator/requirements.txt ]; then pip install -r lambdas/orchestrator/requirements.txt -t /asset-output; fi",
                            "echo $(date +%s) > /asset-output/BUILD_INFO.txt",
                        ]),
                    ],
                ),
            ),
        )
        orchestrator.add_to_role_policy(bedrock_ssm)

        # ---- Secret references (created ahead of HotelAgent; grants applied after)
        google_places_secret = secrets.Secret.from_secret_name_v2(
            self, "GooglePlacesSecret", "/lux/google/places_api_key"
        )
        amadeus_secret = secrets.Secret.from_secret_name_v2(
            self, "AmadeusSecret", "/lux/amadeus/credentials"
        )

        # ---- HotelAgent
        hotel_fn = _lambda.Function(
            self, "HotelAgent",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="handler.lambda_handler",
            timeout=Duration.seconds(20),
            memory_size=512,
            environment=env,
            code=_lambda.Code.from_asset(
                str(repo_root),
                exclude=["cdk", "frontend", "tests", ".git", "README.md"],
                bundling=BundlingOptions(
                    image=_lambda.Runtime.PYTHON_3_12.bundling_image,
                    command=[
                        "bash", "-lc",
                        " && ".join([
                            "mkdir -p /asset-output",
                            "cp -R lambdas/hotel_agent/* /asset-output/",
                            "cp -R shared /asset-output/shared || true",
                            "cp -R tools /asset-output/tools",
                            "if [ -f lambdas/hotel_agent/requirements.txt ]; then pip install -r lambdas/hotel_agent/requirements.txt -t /asset-output; fi",
                            "echo $(date +%s) > /asset-output/BUILD_INFO.txt",
                        ]),
                    ],
                ),
            ),
        )
        hotel_fn.add_to_role_policy(bedrock_ssm)
        # Precise secret grants (HotelAgent only)
        google_places_secret.grant_read(hotel_fn)
        amadeus_secret.grant_read(hotel_fn)

        # ---- BudgetAgent
        budget_fn = _lambda.Function(
            self, "BudgetAgent",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="handler.lambda_handler",
            timeout=Duration.seconds(20),
            memory_size=512,
            environment=env,
            code=_lambda.Code.from_asset(
                str(repo_root),
                exclude=["cdk", "frontend", "tests", ".git", "README.md"],
                bundling=BundlingOptions(
                    image=_lambda.Runtime.PYTHON_3_12.bundling_image,
                    command=[
                        "bash", "-lc",
                        " && ".join([
                            "mkdir -p /asset-output",
                            "cp -R lambdas/budget_agent/* /asset-output/",
                            "cp -R shared /asset-output/shared || true",
                            "cp -R tools /asset-output/tools",
                            "if [ -f lambdas/budget_agent/requirements.txt ]; then pip install -r lambdas/budget_agent/requirements.txt -t /asset-output; fi",
                            "echo $(date +%s) > /asset-output/BUILD_INFO.txt",
                        ]),
                    ],
                ),
            ),
        )
        budget_fn.add_to_role_policy(bedrock_ssm)

        # ---- MCP Server (served at /mcp)
        mcp_fn = _lambda.Function(
            self, "McpServer",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="mcp_server.lambda_handler",  # file: lambdas/orchestrator/mcp_server.py
            timeout=Duration.seconds(20),
            memory_size=512,
            environment={**env, "ALLOWED_ORIGIN": os.getenv("ALLOWED_ORIGIN", "*")},
            code=_lambda.Code.from_asset(
                str(repo_root),
                exclude=["cdk", "frontend", "tests", ".git", "README.md"],
                bundling=BundlingOptions(
                    image=_lambda.Runtime.PYTHON_3_12.bundling_image,
                    command=[
                        "bash", "-lc",
                        " && ".join([
                            "mkdir -p /asset-output",
                            "cp -R lambdas/orchestrator/* /asset-output/",
                            "cp -R shared /asset-output/shared || true",
                            "cp -R tools /asset-output/tools || true",
                            "if [ -f lambdas/orchestrator/requirements.txt ]; then pip install -r lambdas/orchestrator/requirements.txt -t /asset-output; fi",
                            "echo $(date +%s) > /asset-output/BUILD_INFO.txt",
                        ]),
                    ],
                ),
            ),
        )
        mcp_fn.add_to_role_policy(bedrock_ssm)

        # ---- Wiring between Lambdas
        orchestrator.add_environment("HOTEL_FN", hotel_fn.function_name)
        orchestrator.add_environment("BUDGET_FN", budget_fn.function_name)
        hotel_fn.grant_invoke(orchestrator.role)
        budget_fn.grant_invoke(orchestrator.role)

        mcp_fn.add_environment("HOTEL_FN", hotel_fn.function_name)
        mcp_fn.add_environment("BUDGET_FN", budget_fn.function_name)
        hotel_fn.grant_invoke(mcp_fn.role)
        budget_fn.grant_invoke(mcp_fn.role)

        # ---- API Gateway
        http = apigw2.HttpApi(
            self, "LuxApi",
            default_integration=apigw2_integrations.HttpLambdaIntegration("LuxInt", orchestrator),
        )

        # Toggle orchestrator routing: direct vs MCP
        use_mcp = (self.node.try_get_context("useMcp") or os.getenv("USE_MCP_HTTP", "false")).lower() in ("1", "true", "yes")
        orchestrator.add_environment("USE_MCP_HTTP", "true" if use_mcp else "false")
        orchestrator.add_environment("MCP_URL", f"{http.api_endpoint}/mcp")

        # /mcp route
        mcp_integration = apigw2_integrations.HttpLambdaIntegration("McpInt", mcp_fn)
        http.add_routes(
            path="/mcp",
            methods=[apigw2.HttpMethod.POST, apigw2.HttpMethod.OPTIONS],
            integration=mcp_integration,
        )

        # ---- Outputs
        CfnOutput(self, "ApiUrl", value=http.api_endpoint, export_name="LuxApiUrl")
        CfnOutput(self, "McpUrl", value=f"{http.api_endpoint}/mcp", export_name="LuxMcpUrl")
