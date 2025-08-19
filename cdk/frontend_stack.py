from aws_cdk import (
    Stack, CfnOutput, RemovalPolicy, Duration,
    aws_s3 as s3, aws_cloudfront as cf,
    aws_cloudfront_origins as origins, aws_iam as iam
)
from constructs import Construct

class LuxFrontendStack(Stack):
    def __init__(self, scope: Construct, cid: str, **kwargs):
        super().__init__(scope, cid, **kwargs)

        bucket = s3.Bucket(
            self, "LuxFrontendBucket",
            versioned=False,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        oai = cf.OriginAccessIdentity(self, "LuxOAI")

        bucket.add_to_resource_policy(iam.PolicyStatement(
            actions=["s3:GetObject"],
            resources=[bucket.arn_for_objects("*")],
            principals=[iam.CanonicalUserPrincipal(
                oai.cloud_front_origin_access_identity_s3_canonical_user_id
            )],
        ))

        dist = cf.Distribution(
            self, "LuxDist",
            default_behavior=cf.BehaviorOptions(
                origin=origins.S3Origin(bucket, origin_access_identity=oai)
            ),
            default_root_object="index.html",  # 👈 serve index.html at /
            error_responses=[                  # 👇 optional but nice for SPA routing
                cf.ErrorResponse(
                    http_status=403,
                    response_http_status=200,
                    response_page_path="/index.html",
                    ttl=Duration.seconds(0),
                ),
                cf.ErrorResponse(
                    http_status=404,
                    response_http_status=200,
                    response_page_path="/index.html",
                    ttl=Duration.seconds(0),
                ),
            ],
        )

        CfnOutput(self, "FrontendBucketName", value=bucket.bucket_name, export_name="LuxFrontendBucket")
        CfnOutput(self, "FrontendDistributionId", value=dist.distribution_id, export_name="LuxFrontendDistributionId")
        CfnOutput(self, "FrontendDomain", value=dist.domain_name, export_name="LuxFrontendDomain")

