# **Amazon Bedrock Lab: Cycling & Nutrition AI Coach**

This document defines the architecture, project structure, and hands-on lab modules for building a personal generative AI assistant using **Amazon Bedrock**. The project maps directly to the syllabus for the **AWS Certified Generative AI Developer \- Professional** certification while remaining strictly within a **\$100/month budget**.

---

## **1\. Cost Control Architecture (\<\$100/Month)**

To avoid high standing infrastructure costs (such as continuous OpenSearch Serverless clusters or provisioned vector databases), this architecture relies entirely on **serverless, on-demand, and native AWS features**.

| Component | Cost-Effective Choice | Why & Monthly Estimate |
| :---- | :---- | :---- |
| **Vector Store (Knowledge Bases)** | **Amazon S3 Vectors** | **\$0.00 baseline infrastructure cost**. Vectors are stored natively in an S3 Vector bucket and queried directly by Bedrock Knowledge Bases. You pay only for storage and query volume (\<\$1.00/mo). |
| **Foundation Models** | **Claude 3.5 Haiku / Amazon Nova Lite & Pro** | Pay-As-You-Go on-demand inference. Reserve Claude 3.5 Sonnet for evaluation runs (\~\$5–\$15/mo). |
| **Embeddings** | **Amazon Titan Text Embeddings v2** | Dimensions configured to 512 or 1024 to optimize storage and compute (\<\$0.50/mo). |
| **Compute & Hosting** | **AWS Amplify \+ API Gateway (HTTP/REST) \+ Lambda** | Free tier / Pay-per-invocation. Pennies per month. |
| **Storage & Database** | **Amazon DynamoDB (On-Demand)** | Storing daily fitness records, session history, and agent state (\<\$1.00/mo). |

---

## **2\. System Data Flow & Ingestion Architecture**

The application synchronizes automated telemetry and manual daily logs into DynamoDB, exposing an API Gateway \+ Lambda backend to support the React frontend and Bedrock Agent orchestration.

\[Withings API\] \------------┐

                           ├──\> \[API Gateway \+ AWS Lambda\] \---\> \[DynamoDB: Daily Fitness Log\]

\[Strava API\] \--------------┤         (Ingestion & Sync)                    │

\[React Frontend / Amplify\]-┘                                             ▼

                                                          \[Bedrock Agent / Prompt Flows\]

### **Existing Code Integration**

* **Strava & Withings APIs**: Utilizing existing codebases to ingest data into operational DynamoDB tables:  
  * `AthleteDetails`  
  * `starred-segments`  
  * `StravaSegmentEfforts`  
  * `StravaSegments`  
  * `WithingsTelemetry`

* descriptions of the Strava API are available in
  * implementation-details.md
  * strava-tools-data-dictionary.md
  * strava-tools-api-description.json

* descriptions of the Withings API are available in
  * withings-telemetry-openapiv3-description.yaml
  * withings-telemetry-v1-post-implementation-write-up.md


### **Manual Entry Form (Amplify React)**

A frontend view mirroring the Google Sheets fitness log structure:

* **Garmin Daily Metrics**: Training Readiness, Overnight Avg HRV, Resting HR, Sleep Duration, Sleep Score.  
* **Xert Parameters**: Threshold Power (TP), High Intensity Energy (HIE), Peak Power (PP), Lower Threshold Power (LTP), Low/High/Peak XSS.  
* **TrainingPeaks Parameters**: Fitness (CTL), Fatigue (ATL), Form (TSB), TSS, Intensity Factor (IF).  
* **Diet Quality Score (DQS)**: Servings of core food categories following Matt Fitzgerald's *Racing Weight* methodology.

---

## **3\. Bedrock Features & Hands-On Lab Modules**

To maximize educational value, the backend data pipeline and CI/CD are built using Git and AWS CDK, while the core Amazon Bedrock features are **configured manually via the AWS Console**.

### **A. Bedrock Knowledge Bases (S3 Vectors & RAG)**

* **S3 Bucket Structure**: Upload reference documents into a single S3 bucket organized by subfolders:  
  * `s3://<your-bucket>/periodisation/` (Joe Friel's *The Cyclist's Training Bible*)  
  * `s3://<your-bucket>/nutrition/` (Matt Fitzgerald's *Racing Weight*, IOC/ISSN Consensus Statements)  
  * `s3://<your-bucket>/power_models/` (Xert Adaptive Training Advisor & Tri-Factor Model docs, Allen & Coggan power meter principles)  
* **Configuration**: Manually link the S3 bucket and S3 Vector index in the Bedrock Console, selecting Titan Text Embeddings v2 and testing chunking strategies and hybrid search.

### **B. Bedrock Guardrails**

* **Safety & Compliance**: Configure guardrails in the console to prevent unsafe training advice (e.g., advising high-intensity interval sessions when Garmin HRV drops significantly or caloric deficits exceed safe thresholds). Set contextual grounding checks to prevent hallucinations.

### **C. Bedrock Agents & Action Groups (On-Demand Verification)**

* **Agent Core Function**: Acts as your personal AI cycling coach, operating strictly on-demand (no standing ECS instances or idle charges).  
  * *Lab Checkpoint*: Verify in the AWS Billing Console that agent invocations incur zero baseline cost when idle.  
* **Action Groups**: Manually configure OpenAPI schemas connecting the agent to your Lambda functions:  
  1. `get_daily_metrics(date)`: Queries DynamoDB for daily training data.  
  2. `log_dqs_entry(food_items)`: Parses diet logs into DQS point values.  
  3. `calculate_ramp_rate(days)`: Computes chronic training load trends.  
* **Multi-Agent Collaboration**: Optionally configure a Supervisor Agent routing queries between two specialist agents:  
  * *Fueling & Nutrition Agent* (Fitzgerald RAG & DQS)  
  * *Workout Prescription Agent* (Friel/Xert RAG & Power Metrics)

### **D. Bedrock Prompt Flows**

* **Visual Pipeline**: Build a deterministic multi-node flow in the console for morning training recommendations:  
  * Node 1 (Input: HRV, Sleep, TSB) \-\> Node 2 (Knowledge Base Retrieval) \-\> Node 3 (LLM Decision Node) \-\> Node 4 (Guardrail Validation) \-\> Node 5 (Output formatting).

### **E. Prompt Management & Optimization**

* Version and test prompts across models (Claude 3.5 Haiku, Amazon Nova) using dynamic variables (`{{hrv}}`, `{{tsb}}`).

### **F. Model Evaluation (`eval_dataset.jsonl`)**

* Curate a benchmark file of 25–50 test scenarios (e.g., recovery edge cases, DQS calculations) and run automated evaluation and LLM-as-a-Judge scoring in Bedrock.

---

## **4\. Build, Git, CDK & CI/CD Pipeline Deliverables**

1. **Infrastructure as Code (CDK)**:  
   * TypeScript or Python CDK templates defining API Gateway, AWS Lambda functions, DynamoDB tables, and IAM roles for API synchronization and Action Groups.  
2. **CI/CD Pipeline**:  
   * GitHub Actions workflow automating linting, testing, and deployment to AWS Amplify (frontend) and Lambda/API Gateway (backend).  
3. **Evaluation & Documentation**:  
   * Stored `eval_dataset.jsonl` benchmark suite in S3 for ongoing model and prompt tuning.

This solution should be built in the us-east-1 AWS region