import { CfnOutput, Duration, RemovalPolicy, Stack, StackProps } from 'aws-cdk-lib';
import * as apigw from 'aws-cdk-lib/aws-apigatewayv2';
import { HttpJwtAuthorizer } from 'aws-cdk-lib/aws-apigatewayv2-authorizers';
import * as cognito from 'aws-cdk-lib/aws-cognito';
import { Construct } from 'constructs';

/**
 * The shared HTTP API and the single-user Cognito pool that protects it.
 * Other stacks attach their own routes, so this stack owns no Lambda code.
 */
export class ApiStack extends Stack {
  readonly httpApi: apigw.HttpApi;
  readonly authorizer: HttpJwtAuthorizer;
  readonly userPool: cognito.UserPool;
  readonly userPoolClient: cognito.UserPoolClient;

  constructor(scope: Construct, id: string, props?: StackProps) {
    super(scope, id, props);

    // Self sign-up is off: create your one user with `aws cognito-idp admin-create-user`.
    this.userPool = new cognito.UserPool(this, 'UserPool', {
      userPoolName: 'cycling-coach-users',
      selfSignUpEnabled: false,
      signInAliases: { email: true },
      passwordPolicy: { minLength: 12, requireSymbols: false },
      accountRecovery: cognito.AccountRecovery.EMAIL_ONLY,
      removalPolicy: RemovalPolicy.RETAIN,
    });

    // Public SPA client: no secret; Amplify Auth signs in with SRP.
    this.userPoolClient = this.userPool.addClient('WebClient', {
      userPoolClientName: 'cycling-coach-web',
      generateSecret: false,
      authFlows: { userSrp: true },
      accessTokenValidity: Duration.hours(1),
      idTokenValidity: Duration.hours(1),
      refreshTokenValidity: Duration.days(30),
    });

    this.httpApi = new apigw.HttpApi(this, 'HttpApi', {
      apiName: 'cycling-coach-api',
      description: 'Daily log, Strava sync/OAuth and Withings read endpoints',
      // Bearer tokens (not cookies) are used, so any origin is safe here and the
      // Amplify domain doesn't need to be known before the frontend stack exists.
      corsPreflight: {
        allowOrigins: ['*'],
        allowMethods: [apigw.CorsHttpMethod.GET, apigw.CorsHttpMethod.PUT, apigw.CorsHttpMethod.POST],
        allowHeaders: ['Authorization', 'Content-Type'],
        maxAge: Duration.hours(1),
      },
    });

    this.authorizer = new HttpJwtAuthorizer(
      'CognitoAuthorizer',
      `https://cognito-idp.${this.region}.amazonaws.com/${this.userPool.userPoolId}`,
      { jwtAudience: [this.userPoolClient.userPoolClientId] },
    );

    new CfnOutput(this, 'ApiUrl', { value: this.httpApi.apiEndpoint });
    new CfnOutput(this, 'UserPoolId', { value: this.userPool.userPoolId });
    new CfnOutput(this, 'UserPoolClientId', { value: this.userPoolClient.userPoolClientId });
  }
}
