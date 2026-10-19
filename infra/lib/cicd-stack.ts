import { CfnOutput, Duration, Stack, StackProps } from 'aws-cdk-lib';
import * as iam from 'aws-cdk-lib/aws-iam';
import { Construct } from 'constructs';

export interface CicdStackProps extends StackProps {
  /** "owner/repo" on GitHub. */
  readonly githubRepo: string;
  readonly amplifyAppId: string;
  readonly kbSourceBucketArn: string;
  readonly evalBucketArn: string;
}

/**
 * GitHub Actions -> AWS via OIDC (no long-lived keys). The deploy role can only
 * be assumed by jobs running in this repository's `production` environment.
 * (A job that declares `environment:` gets an OIDC subject of
 * `repo:<owner>/<repo>:environment:<name>`, not the branch ref.) Restrict that
 * environment to the `main` branch in GitHub's environment settings.
 *
 * It can deploy CDK (by assuming the CDK bootstrap roles), deploy the Amplify
 * frontend and sync schemas/eval data to S3. It has NO Bedrock permissions:
 * Bedrock resources are built by hand in the console.
 */
export class CicdStack extends Stack {
  constructor(scope: Construct, id: string, props: CicdStackProps) {
    super(scope, id, props);

    // One OIDC provider per account; import it if it already exists by setting
    // context `githubOidcProviderArn`.
    const existingArn = this.node.tryGetContext('githubOidcProviderArn') as string | undefined;
    const provider = existingArn
      ? iam.OpenIdConnectProvider.fromOpenIdConnectProviderArn(this, 'GithubOidc', existingArn)
      : new iam.OpenIdConnectProvider(this, 'GithubOidc', {
          url: 'https://token.actions.githubusercontent.com',
          clientIds: ['sts.amazonaws.com'],
        });

    const role = new iam.Role(this, 'DeployRole', {
      roleName: 'cycling-coach-github-deploy',
      maxSessionDuration: Duration.hours(1),
      assumedBy: new iam.WebIdentityPrincipal(provider.openIdConnectProviderArn, {
        StringEquals: {
          'token.actions.githubusercontent.com:aud': 'sts.amazonaws.com',
          'token.actions.githubusercontent.com:sub': `repo:${props.githubRepo}:environment:production`,
        },
      }),
    });

    // `cdk deploy` works by assuming the bootstrap roles.
    role.addToPolicy(
      new iam.PolicyStatement({
        actions: ['sts:AssumeRole'],
        resources: [`arn:aws:iam::${this.account}:role/cdk-hnb659fds-*-${this.account}-${this.region}`],
      }),
    );

    role.addToPolicy(
      new iam.PolicyStatement({
        actions: ['amplify:CreateDeployment', 'amplify:StartDeployment', 'amplify:GetJob'],
        resources: [`arn:aws:amplify:${this.region}:${this.account}:apps/${props.amplifyAppId}/*`],
      }),
    );

    role.addToPolicy(
      new iam.PolicyStatement({
        actions: ['cloudformation:DescribeStacks'],
        resources: [`arn:aws:cloudformation:${this.region}:${this.account}:stack/*`],
      }),
    );

    role.addToPolicy(
      new iam.PolicyStatement({
        actions: ['s3:ListBucket', 's3:GetObject', 's3:PutObject', 's3:DeleteObject'],
        resources: [
          props.kbSourceBucketArn,
          `${props.kbSourceBucketArn}/schemas/*`,
          props.evalBucketArn,
          `${props.evalBucketArn}/datasets/*`,
        ],
      }),
    );

    new CfnOutput(this, 'DeployRoleArn', { value: role.roleArn });
  }
}
