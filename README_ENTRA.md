# Google Cloud Creative Studio: Deployment & Entra ID Setup Guide

This guide provides step-by-step instructions for cloning, configuring, and deploying the Google Cloud Creative Studio Platform to Google Cloud Platform (GCP) with authentication backed by Microsoft Entra ID (formerly Azure Active Directory) via Workforce Identity Federation and IAP.

---

## 📋 Prerequisites

Before you begin, ensure you have the following installed and configured:
*   **Git**: For cloning the repository.
*   **Google Cloud CLI (`gcloud`)**: Authenticated to your GCP account.
*   **Terraform**: Version 1.5.0 or later (if running manually, though the bootstrap script handles execution).
*   **An active GCP Project** (referred to as `[PROJECT_NAME]` in this guide).
*   **Owner permissions** on the GCP Project.
*   **Administrator access** to a Microsoft Entra ID Tenant (to create App Registrations).

---

## 🛠️ Step 1: Clone the Repository

Clone the repository and checkout the latest branch containing the IAP and Entra integration changes.

1.  Open your terminal.
2.  Clone the repository:
    ```bash
    git clone https://github.com/GoogleCloudPlatform/gcc-creative-studio.git
    cd gcc-creative-studio
    ```
3.  Switch to the integration branch:
    ```bash
    git checkout feature/entra-authentication-final
    ```

---

## 🔑 Step 2: Configure Microsoft Entra ID (Azure AD)

You need to register the Creative Studio application in your Microsoft Entra Tenant to obtain the client credentials needed for authentication.

### 1. Create App Registration
1.  Sign in to the [Microsoft Entra admin center](https://entra.microsoft.com/) as at least an Application Administrator.
2.  Browse to **Identity** > **Applications** > **App registrations** and select **New registration**.
3.  Enter a name for the application (e.g., `Creative Studio Dev`).
4.  Under **Supported account types**, select **Accounts in this organizational directory only (Single tenant)**.
5.  Under **Redirect URI**, select **Single-page application (SPA)** (for MSAL frontend login) and enter the URL where the app will be hosted:
    *   For local testing: `http://localhost:4200/`
    *   For deployed app: `https://[YOUR_DOMAIN_OR_IP]/` (or your custom domain).
    *   *Note: You can add multiple redirect URIs later.*
6.  Select **Register**.

### 2. Collect Client and Tenant IDs
1.  After registration, you will be redirected to the App's **Overview** page.
2.  Copy the following values and save them:
    *   **Application (client) ID**
    *   **Directory (tenant) ID**

### 3. Generate Client Secret
1.  In the left navigation panel, select **Certificates & secrets** > **Client secrets** > **New client secret**.
2.  Add a description (e.g., `Creative Studio GCP Deployment`) and select an expiration period.
3.  Select **Add**.
4.  **CRITICAL**: Copy the **Value** of the secret immediately. It will be hidden permanently once you navigate away from this page.

### 4. Enable ID Token Issuance (for IAP / WIF)
1.  Select **Authentication** in the left panel.
2.  Under **Implicit grant and hybrid flows**, ensure **ID tokens (used for implicit and hybrid flows)** is **checked**.
3.  Select **Save**.

---

## 🛡️ Step 3: Create Google Workforce OAuth Client for IAP

Standard Google Accounts OAuth clients cannot be used with Workforce Identity Federation. Instead, you must create a dedicated Workforce Identity OAuth Client using the `gcloud` CLI. **Do NOT use the GCP Console to create this client**, as it will incorrectly prompt you to configure a consent screen.

1.  Run the following command to create the global Workforce OAuth client (replace `YOUR_PROJECT_ID` with your GCP project ID):
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
2.  Describe the client to retrieve the system-generated **Client ID**:
    ```bash
    gcloud iam oauth-clients describe cs-wif-oauth-client \
        --project=YOUR_PROJECT_ID \
        --location=global
    ```
    *Copy the **`clientId`** value from the output (e.g., `ae1b3ac35...`).*
3.  Update the OAuth client's redirect URI with its own generated Client ID:
    ```bash
    gcloud iam oauth-clients update cs-wif-oauth-client \
        --project=YOUR_PROJECT_ID \
        --location=global \
        --allowed-redirect-uris="https://iap.googleapis.com/v1/oauth/clientIds/YOUR_GENERATED_CLIENT_ID:handleRedirect"
    ```
    *(Replace `YOUR_GENERATED_CLIENT_ID` with the Client ID from the previous step).*
4.  Generate the **Client Secret**:
    ```bash
    gcloud iam oauth-clients credentials create cs-wif-oauth-credential \
        --oauth-client=cs-wif-oauth-client \
        --project=YOUR_PROJECT_ID \
        --location=global
    ```
5.  Retrieve and save the generated **Client Secret**:
    ```bash
    gcloud iam oauth-clients credentials describe cs-wif-oauth-credential \
        --oauth-client=cs-wif-oauth-client \
        --project=YOUR_PROJECT_ID \
        --location=global
    ```
    *Copy the **`clientSecret`** value from the output.*

Keep both the **Client ID** and **Client Secret** handy for the next step.

---

## 🚀 Step 4: Deploy to Google Cloud Platform (GCP)

The project includes an automated `bootstrap.sh` script that handles the configuration of Terraform variables, GCP Secret Manager initialization, and deployment.

1.  Initialize your Google Cloud application default credentials:
    ```bash
    gcloud auth application-default login
    ```
2.  Make the bootstrap script executable:
    ```bash
    chmod +x bootstrap.sh
    ```
3.  Run the bootstrap script:
    ```bash
    ./bootstrap.sh
    ```
4.  Follow the interactive prompts during the execution of the script:
    *   **GCP Project ID**: Enter your target Google Cloud Project ID (e.g., `my-project-123`). The script will attempt to set this as your active gcloud project.
    *   **Environment Name**: Enter a name for your deployment environment (default: `dev-infra`). This defines the folder name under `infra/environments/` where your specific configuration will be stored.
    *   **GitHub Repository URL**: Enter the URL of your forked repository (e.g., `https://github.com/your-user/gcc-creative-studio.git`).
    *   **Branch Name**: Enter the git branch to deploy from (default: `main`). For testing the Entra integration, ensure you use `feature/entra-authentication-final` or the branch where you have these changes.
    *   **Authentication Choice**: Type **2** and press Enter to select **Microsoft Entra ID**.
    *   **Entra Client ID**: Paste the *Application (client) ID* of the App Registration you created in Step 2.
    *   **Entra Tenant ID**: Paste the *Directory (tenant) ID* of your Entra Tenant collected in Step 2.
    *   **Entra Client Secret**: Paste the *Client Secret Value* generated in Step 2. (Input is hidden for security).
    *   **Domain Name**: Enter the domain name or IP where the app will be hosted. 
        *   *If you do not have a custom domain yet*, you can use a temporary placeholder like `127.0.0.1` or `temp.example.com`. After the deployment finishes and you get the Load Balancer IP, you can re-run the script or update the `.tfvars` file to use `[LB_IP].nip.io` for testing.
    *   **GCP Organization ID**: Enter your GCP Organization numerical ID. You can find this in the GCP Console under the project selector or by running `gcloud organizations list`. This is required to set up Workforce Identity Federation.
    *   **IAP OAuth Client ID**: Paste the Client ID generated in Step 3.
    *   **IAP OAuth Client Secret**: Paste the Client Secret generated in Step 3.

### ⚠️ Crucial Manual Actions Required During Bootstrapping

The script will automate almost everything, but it will pause at two points to require manual actions in your web browser. **You must complete these before the script can proceed.**

#### Action A: Link your GCP Project to Firebase
Terraform requires your project to be associated with Firebase to provision Firebase services. Since this requires accepting legal terms, it must be done manually:
1.  The script will display a URL: `https://console.firebase.google.com/?project=[YOUR_PROJECT_ID]`
2.  Open this URL in your browser (ensure you are logged in with the same account used for `gcloud`).
3.  Click **"Add Firebase"** (or **"Get Started"** / **"Link Project"** depending on your console state).
4.  Follow the prompts to confirm the linking and accept the terms of service.
5.  Once completed, return to your terminal and press **[Enter]** to resume the script.

#### Action B: Create a GitHub Connection in Cloud Build
Cloud Build needs authorization to access your GitHub repository to pull code for building.
1.  The script will display a URL: `https://console.cloud.google.com/cloud-build/connections/create?project=[YOUR_PROJECT_ID]`
2.  Open this URL in your browser.
3.  Select **"GitHub (Cloud Build GitHub App)"** and click **"Continue"**.
4.  You will be redirected to GitHub to authorize the Google Cloud Build application.
5.  Select your GitHub account/organization and choose to grant access to **all repositories** or specifically to your **forked `gcc-creative-studio` repository**.
6.  After authorizing, you will be redirected back to the GCP Console, and a connection will be created. Copy the connection name (typically it looks like a short string you provided, or you can check the connection list).
7.  Return to your terminal, and when prompted for **"Connection Name"**, paste the name (default fallback is `creative-studio`).

### 📦 Automatic Post-Deployment Steps
After you complete the manual steps, the script will:
1.  Initialize and run **Terraform** to provision all infrastructure (Cloud Run services, Global Load Balancer, Cloud SQL, Secret Manager, Cloud Storage, WIF Workforce Pools, and IAP configurations).
2.  **Populate Secrets:** Automatically fetch Firebase configuration values and write them as secrets to Secret Manager.
3.  **Database Migration & Seeding:** Start a secure Cloud SQL proxy locally, run database migrations, and seed initial templates, VTO models, and assets into the database and GCS bucket.

The script execution is complete when you see a green success message with the **Load Balancer IP** and **IAP Expected Audience**. Keep these values handy for the next steps.

---

## 🔒 Step 4.5: Configure Email Domain Allowlist (Optional)

By default, any user authenticated via your Entra ID tenant can access the application. You can restrict access to specific email domains (e.g., only allow `yourcompany.com` or specific partner domains) using the application-level allowlist.

1.  Locate your environment's `.tfvars` file (created after running the bootstrap script):
    *   Path: `infra/environments/[YOUR_ENV_NAME]/[YOUR_ENV_NAME].tfvars` (e.g., `infra/environments/dev-infra/dev-infra.tfvars`).
2.  Open the file and locate the `be_env_vars` block.
3.  Under the `development` (or `production`) section, find the `IDENTITY_PLATFORM_ALLOWED_ORGS` variable.
4.  Set it to a comma-separated list of allowed domains (no spaces):
    ```hcl
    be_env_vars = {
      common = {
        LOG_LEVEL = "INFO"
      }
      development = {
        ENVIRONMENT  = "development"
        GOOGLE_TOKEN_AUDIENCE = "YOUR_OAUTH_WEB_CLIENT_ID_HERE"
        IDENTITY_PLATFORM_ALLOWED_ORGS = "yourcompany.com,partnerdomain.com"
      }
      # ...
    }
    ```
    *   *Note: If left empty (`""`), any authenticated domain is allowed.*
5.  Apply the changes to your deployment:
    *   Navigate to your environment directory and run:
        ```bash
        cd infra/environments/[YOUR_ENV_NAME]
        terraform apply -var-file="[YOUR_ENV_NAME].tfvars"
        ```
    *   The backend Cloud Run service will redeploy with the new environment variables. Subsequent login attempts from non-allowlisted domains will be rejected.

---

## 🌐 Step 5: Add a Custom Domain

To configure a custom domain instead of using the default IP-based hostname:

### 1. Identify the Load Balancer IP
Once the Terraform deployment finishes successfully, it will output the external IP address of the Global Load Balancer created for IAP. You can also find it in the console:
1.  Go to **Network Services** > **Load Balancing** in the GCP Console.
2.  Select the load balancer created for your deployment (typically named `cstudio-lb-development` or similar).
3.  Locate the Frontend IP address.

### 2. Configure DNS
1.  Log in to your Domain Registrar (e.g., Google Domains, GoDaddy, Cloudflare).
2.  Navigate to the DNS management panel for your custom domain.
3.  Create an **A Record**:
    *   **Host/Name**: `@` (for root domain) or `studio` (for a subdomain like `studio.yourdomain.com`).
    *   **Value/Points to**: The Frontend IP address of the GCP Load Balancer identified above.
    *   **TTL**: Default (e.g., 3600 seconds).

### 3. Update the App Configurations
Once DNS propagates, you must update the application to recognize the new domain:
1.  Re-run `./bootstrap.sh` and provide your new custom domain (e.g. `studio.yourdomain.com`) when prompted. This updates Terraform and regenerates the SSL certificate for the Load Balancer.
2.  Update your Microsoft Entra App Registration (Step 2) to include `https://studio.yourdomain.com/` as an allowed **Redirect URI**.
