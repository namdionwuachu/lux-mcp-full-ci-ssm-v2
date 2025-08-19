from aws_cdk import (
    Stack, Duration, CfnOutput,
    aws_lambda as _lambda,
    aws_apigatewayv2 as apigw2,
    aws_apigatewayv2_integrations as apigw2_integrations,
    aws_iam as iam,
)
from constructs import Construct
import os
class LuxStack(Stack):
    def __init__(self, scope: Construct, cid: str, **kwargs):
        super().__init__(scope, cid, **kwargs)
        policy = iam.PolicyStatement(actions=[
                "bedrock:InvokeModel","bedrock:InvokeModelWithResponseStream",
                "secretsmanager:GetSecretValue","ssm:GetParameter"
            ], resources=["*"])
        env = {
            "AMADEUS_BASE_URL": os.getenv("AMADEUS_BASE_URL","https://test.api.amadeus.com"),
            "AMADEUS_SECRET_NAME": os.getenv("AMADEUS_SECRET_NAME","/lux/amadeus/credentials"),
            # Scraping scaffold (OFF by default)
            "HOTEL_PROVIDER_ORDER": os.getenv("HOTEL_PROVIDER_ORDER","amadeus"),
            "ALLOWLIST_DOMAINS": os.getenv("ALLOWLIST_DOMAINS",""),
        }
        orchestrator=_lambda.Function(self,"Orchestrator",runtime=_lambda.Runtime.PYTHON_3_12,handler="handler.lambda_handler",
                                      code=_lambda.Code.from_asset("../lambdas/orchestrator"),timeout=Duration.seconds(20),memory_size=512,environment=env)
        orchestrator.add_to_role_policy(policy)
        hotel_fn=_lambda.Function(self,"HotelAgent",runtime=_lambda.Runtime.PYTHON_3_12,handler="handler.lambda_handler",
                                  code=_lambda.Code.from_asset("../lambdas/hotel_agent"),timeout=Duration.seconds(20),memory_size=512,environment=env)
        hotel_fn.add_to_role_policy(policy)
        budget_fn=_lambda.Function(self,"BudgetAgent",runtime=_lambda.Runtime.PYTHON_3_12,handler="handler.lambda_handler",
                                   code=_lambda.Code.from_asset("../lambdas/budget_agent"),timeout=Duration.seconds(20),memory_size=512,environment=env)
        budget_fn.add_to_role_policy(policy)
        http=apigw2.HttpApi(self,"LuxApi",default_integration=apigw2_integrations.HttpLambdaIntegration("LuxInt", orchestrator))
        CfnOutput(self,"ApiUrl",value=http.api_endpoint,export_name="LuxApiUrl")
