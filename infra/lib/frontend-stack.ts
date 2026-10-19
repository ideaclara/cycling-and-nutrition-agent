import { CfnOutput, Stack, StackProps } from 'aws-cdk-lib';
import * as amplify from 'aws-cdk-lib/aws-amplify';
import { Construct } from 'constructs';

export interface FrontendStackProps extends StackProps {
  readonly apiUrl: string;
  readonly userPoolId: string;
  readonly userPoolClientId: string;
}

/**
 * Amplify Hosting app with no repository connection ("manual deploy").
 * GitHub Actions builds frontend/ and uploads the zip with
 * `aws amplify create-deployment` + `start-deployment`.
 *
 * The VITE_* values are recorded on the branch for reference; the build reads
 * them from the stack outputs (see .github/workflows/deploy.yml).
 */
export class FrontendStack extends Stack {
  readonly appId: string;

  constructor(scope: Construct, id: string, props: FrontendStackProps) {
    super(scope, id, props);

    const app = new amplify.CfnApp(this, 'App', {
      name: 'cycling-coach',
      platform: 'WEB',
      customRules: [
        // Single-page app: serve index.html for any path without a file extension.
        { source: '</^[^.]+$|\\.(?!(css|gif|ico|jpg|js|png|txt|svg|woff|woff2|ttf|map|json|webp)$)([^.]+$)/>', target: '/index.html', status: '200' },
      ],
    });

    this.appId = app.attrAppId;

    const branch = new amplify.CfnBranch(this, 'MainBranch', {
      appId: app.attrAppId,
      branchName: 'main',
      stage: 'PRODUCTION',
      environmentVariables: [
        { name: 'VITE_API_BASE_URL', value: props.apiUrl },
        { name: 'VITE_USER_POOL_ID', value: props.userPoolId },
        { name: 'VITE_USER_POOL_CLIENT_ID', value: props.userPoolClientId },
      ],
    });

    new CfnOutput(this, 'AmplifyAppId', { value: app.attrAppId });
    new CfnOutput(this, 'AmplifyBranch', { value: branch.branchName });
    new CfnOutput(this, 'AppUrl', { value: `https://main.${app.attrDefaultDomain}` });
  }
}
