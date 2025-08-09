#!/usr/bin/env python3
import aws_cdk as cdk
from lux_stack import LuxStack
from frontend_stack import LuxFrontendStack
app = cdk.App()
env = cdk.Environment(region="us-east-1")
LuxStack(app, "LuxStack", env=env)
LuxFrontendStack(app, "LuxFrontendStack", env=env)
app.synth()
