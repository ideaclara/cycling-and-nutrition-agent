# **Withings Health Telemetry V1: Post-Implementation Architecture & Write-Up**

## **1\. Executive Summary & System Overview**

The **Withings Health Telemetry Platform** is a serverless, end-to-end data ingestion pipeline and high-performance analytics web dashboard. It captures, stores, indexes, and visualizes multi-modal physiological metrics transmitted by Withings smart scales (Body Scan and Body Cardio).

Operating across three primary architectural tiers:

1. **Ingestion & Storage Tier**: EventBridge schedules and Step Functions orchestrate OAuth2 token exchange with Secrets Manager, paginating Withings API endpoints (`/measure?action=getmeas`), applying SI conversions, and consolidating multi-packet sessions into Amazon DynamoDB (`WithingsTelemetry`).  
2. **Read-Optimized API Tier**: An Amazon API Gateway HTTP API (v2) integrated with a read-optimized Python 3.11 Lambda function featuring exhaustive partition scanning and zero-value session filtering.  
3. **Frontend Analytics Tier**: A high-performance Vite \+ React (TypeScript) application hosted on AWS Amplify Hosting. It features a TanStack Table log view and three synchronized, gap-free 6-month Recharts line charts (Total Body Mass, Fat Mass, and Muscle Mass) with dynamic rolling averages (3–60 days).

---

## **2\. Storage Tier & DynamoDB Schema (`WithingsTelemetry`)**

* **Target Region**: `eu-west-2` (London)  
* **Billing Mode**: Pay-Per-Request (On-Demand)  
* **Partition Key (`PK`)**: `USER#<userid>` (e.g., `USER#31179536`)  
* **Sort Key (`SK`)**: `WITHINGS#MEAS#<timestamp>` (zero-padded 10-digit UTC Unix epoch)

### **Consolidated Session Attributes (`MEASUREMENT_SESSION`)**

| Attribute Name | DynamoDB Type | Description & Precision |
| :---- | :---- | :---- |
| `timestamp` | Number | UTC Unix epoch formatted to local UK time (BST/GMT) |
| `weight_kg` | Number | Total body mass (`XX.XX kg`) |
| `fat_ratio_pct` | Number | Body fat percentage (`XX.X %`) |
| `fat_mass_weight_kg` | Number | Absolute fat mass (`XX.XX kg`) |
| `fat_free_mass_kg` | Number | Fat-free mass (`XX.XX kg`) |
| `muscle_mass_kg` | Number | Skeletal muscle mass (`XX.XX kg`) |
| `hydration_kg` | Number | Total body water (`XX.XX kg`) |
| `bone_mass_kg` | Number | Bone mineral mass (`XX.XX kg`) |
| `heart_pulse_bpm` | Number | Resting heart rate (`XX bpm`) |
| `pulse_wave_velocity_raw_ms` | Number | Unadjusted aortic-femoral transit speed (`X.XX m/s`) |
| `pulse_wave_velocity_normalized_ms` | Number | Heart-rate normalized PWV (`X.XX m/s`) |
| `vascular_age_yrs` | Number | Biological vascular age (`XX.X yrs`) |
| `device_model` | String | Scale hardware model (`Body Cardio`, `Body Scan`) |
| `measure_group_ids` | List (Number) | Raw Withings measurement group IDs consolidated per session |

---

## **3\. API Gateway & Lambda Read Contract**

* **Base URL**: `https://<api-id>.execute-api.eu-west-2.amazonaws.com`  
* **Route**: `GET /telemetry/measures`  
* **Query Parameters**:  
  - `userId` (string, optional): Defaults to `31179536`.  
  - `limit` (integer, optional): Maximum records to return (up to `1000`).  
* **Behavior**: Uses descending sort order (`ScanIndexForward=False`) to pull partition-wide chronological records, skipping unpopulated ghost packets and returning clean consolidated JSON payloads.

---

## **4\. Frontend Application Architecture (Vite \+ React \+ TypeScript)**

Hosted via **AWS Amplify Hosting**, the frontend provides two primary views:

1. **Trends & Rolling Averages**: Three synchronized, gap-free 6-month time-series charts (Recharts) for Total Body Mass (Blue), Fat Mass (Red), and Muscle Mass (Green) in kilograms. Features an interactive 3 to 60-day moving average slider, whole-integer Y-axis grid increments (no forced zero baseline), and `connectNulls=true` for continuous timelines.  
2. **Table Log**: A TanStack Table interface providing sortable, formatted historical logs with strict decimal precision and distinct columns for Raw vs. Normalized PWV.

---

## **5\. Automated Delivery Architecture: AWS CodePipeline & CDK**

* **IaC Framework**: AWS CDK (`@aws-cdk/pipelines`)  
* **Repository**: `ideaclara/withings-data-on-aws` (branch `main`)  
* **Pipeline Flow**:  
  - **Source**: GitHub webhook integration.  
  - **Synth**: Synthesizes CloudFormation templates.  
  - **Self-Mutate**: Pipeline updates its own definition when IaC changes.  
  - **Prod Stage (`Prod-WithingsTelemetryStack`)**: Provisions DynamoDB, API Gateway, read Lambda functions, and AWS Amplify static hosting (injecting `VITE_API_BASE_URL` automatically).