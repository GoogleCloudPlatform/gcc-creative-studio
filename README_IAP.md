# Securing and Deploying with Identity-Aware Proxy (IAP) & Microsoft Entra ID

This guide explains how to secure and deploy the **Google Cloud Creative Studio Platform** in a Google Cloud project using **Identity-Aware Proxy (IAP)** federated with **Microsoft Entra ID (Azure AD)** via **Workforce Identity Federation (WIF)**.

---

## Architecture Overview
By securing the application with IAP and Workforce Identity Federation, you completely avoid having to provision or sync user identity accounts into Google Cloud. 

1. An external user attempts to access the HTTPS Load Balancer domain.
2. IAP intercepts the request and checks for authentication.
3. If unauthenticated, IAP redirects the user to Google's Workforce Identity sign-in portal.
4. The sign-in portal redirects the user to your organization's Microsoft Entra ID sign-in page.
5. Upon successful Entra ID authentication, the user is redirected back to Google IAP and authorized based on IAM policy.

---

## Prerequisites
Before beginning the deployment, ensure you have the following:

### 1. Google Cloud Platform (GCP)
* A **GCP Organization** (Workforce Identity Pools cannot be created in standalone projects).
* Your GCP **Organization ID** (numeric). You can find this by running:
  ```bash
  gcloud organizations list
  ```
* A target **GCP Project** inside that organization.
* The **Workforce Pool Admin** (`roles/iam.workforcePoolAdmin`) role granted to your GCP user account at the **Organization level**.

### 2. Microsoft Entra ID (Azure AD)
* An active Microsoft Entra tenant.
* Access to the Azure Portal with permissions to create **App Registrations**.

---

## Step-by-Step Setup Guide

### Step 1: Microsoft Entra ID App Registration
1. Log in to the [Azure Portal](https://portal.azure.com/).
2. Navigate to **Microsoft Entra ID** (or **Azure Active Directory**).
3. In the left navigation, select **App registrations** > **New registration**.
4. Configure the app registration:
   * **Name**: e.g., `GCP Workforce Identity Client`
   * **Supported account types**: Select "Accounts in this organizational directory only" (Single Tenant).
   * **Redirect URI (optional)**: Select **Web** and add the following global Google sign-in callback URL:
     ```
     https://auth.cloud.google/signin-callback/locations/global/workforcePools/cs-workforce-pool/providers/entra-provider
     ```
     *(Note: If you change the Workforce Pool ID or Provider ID, update the path accordingly: `/workforcePools/<POOL_ID>/providers/<PROVIDER_ID>`).*

5. Click **Register**.
6. On the application Overview page, copy and save these values:
   * **Application (client) ID**
   * **Directory (tenant) ID**
7. Navigate to **Certificates & secrets** in the left menu.
8. Under the **Client secrets** tab, click **New client secret**.
9. Add a description, choose an expiration period, and click **Add**.
10. Copy and save the secret **Value** (do not copy the Secret ID). *Note: This value is only shown once upon creation, so save it immediately.*


---

### Step 2: Create a Google Workforce OAuth Client for IAP
Standard Google Accounts OAuth clients cannot be used with Workforce Identity Federation. Instead, you must create a dedicated Workforce Identity OAuth Client using the `gcloud` CLI.

1. Run the following command to create the global Workforce OAuth client (replace `YOUR_PROJECT_ID` with your GCP project ID):
   ```bash
   gcloud iam oauth-clients create cs-wif-oauth-client \
       --project=YOUR_PROJECT_ID \
       --location=global \
       --client-type="confidential-client" \
       --display-name="Creative Studio IAP WIF Client" \
       --allowed-grant-types="authorization-code-grant" \
       --allowed-scopes="openid,email,https://www.googleapis.com/auth/cloud-platform" \
       --allowed-redirect-uris="https://example.com/callback"

   ```
2. Describe the newly created client to retrieve the system-generated **Client ID**:
   ```bash
   gcloud iam oauth-clients describe cs-wif-oauth-client \
       --project=YOUR_PROJECT_ID \
       --location=global
   ```
   *Copy the **`clientId`** value from the output (it will look like a UUID, e.g., `ae1b3ac35-542f-4a97-b7ac-be4fb6160c2e`).*

3. Update the OAuth client's redirect URI to use its own generated Client ID redirect handler:
   ```bash
   gcloud iam oauth-clients update cs-wif-oauth-client \
       --project=YOUR_PROJECT_ID \
       --location=global \
       --allowed-redirect-uris="https://iap.googleapis.com/v1/oauth/clientIds/YOUR_GENERATED_CLIENT_ID:handleRedirect"
   ```
   *(Replace `YOUR_GENERATED_CLIENT_ID` with the Client ID copied in the previous step).*

4. Generate the Client Secret for this Workforce client:
   ```bash
   gcloud iam oauth-clients credentials create cs-wif-oauth-credential \
       --oauth-client=cs-wif-oauth-client \
       --project=YOUR_PROJECT_ID \
       --location=global
   ```
5. Retrieve and save the generated **Client Secret**:
   ```bash
   gcloud iam oauth-clients credentials describe cs-wif-oauth-credential \
       --oauth-client=cs-wif-oauth-client \
       --project=YOUR_PROJECT_ID \
       --location=global
   ```
   *Copy the **`clientSecret`** value from the output (it will look like a Google secret key starting with `GOCSPX-`).*


---

### Step 3: Populate Terraform Configuration (`dev-infra.tfvars`)
To enable WIF and IAP, configure these variables in your target environment's `.tfvars` file (e.g., `infra/environments/dev-infra/dev-infra.tfvars`):

```hcl
# --- IAP Credentials ---
iap_oauth2_client_id     = "YOUR_GOOGLE_CLIENT_ID"
iap_oauth2_client_secret = "YOUR_GOOGLE_CLIENT_SECRET"
domain_name              = "YOUR_DOMAIN_NAME" # (e.g., "creative.yourcompany.com" or "8.8.8.8.nip.io")

# --- Workforce Identity Federation (WIF) ---
org_id              = "YOUR_GCP_ORGANIZATION_ID_NUMERIC"
entra_client_id     = "YOUR_MICROSOFT_ENTRA_CLIENT_ID"
entra_tenant_id     = "YOUR_MICROSOFT_ENTRA_TENANT_ID"
entra_client_secret = "YOUR_MICROSOFT_ENTRA_CLIENT_SECRET"

# --- Authorization Access Rules ---

# You can authorize individual Entra ID users, entire domains, or all users in the pool.
# Use wildcard '*' to allow any user authenticated via the Workforce pool to access the application:
iap_access_members = [
  "principalSet://iam.googleapis.com/locations/global/workforcePools/cs-workforce-pool/*"
]
```

---

### Step 4: Deploy using Terraform
Initialize and apply the Terraform configuration inside your environment directory:
```bash
# Initialize Terraform
terraform init

# Apply the infrastructure configuration
terraform apply -var-file=dev-infra.tfvars
```
Terraform will automatically:
1. Create a Workforce Identity Pool (`cs-workforce-pool`).
2. Register Microsoft Entra ID as the OIDC provider inside the pool.
3. Configure the HTTP Load Balancer with Managed SSL Certificates.
4. Enable IAP on the Load Balancer's backend and associate it with the Workforce pool.
5. Create the IAM bindings granting access to the workforce principals.

---

### Step 5: Test and Access the App
1. Wait 5-10 minutes for your SSL certificates and Load Balancer to propagate globally.
2. Navigate to your domain in the browser (e.g., `https://YOUR_DOMAIN_NAME`).
3. You will be redirected to Google's Workforce Single Sign-On page.
4. Select your identity provider or log in. It will redirect you to Microsoft Entra's sign-in screen.
5. Enter your corporate email and password.
6. Once authenticated, Entra will redirect you back to Google IAP, and IAP will let you access Creative Studio!
