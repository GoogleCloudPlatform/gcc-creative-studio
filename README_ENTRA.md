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
    git clone https://github.com/eric-lyons/gcc-creative-studio.git
    cd gcc-creative-studio
    ```
3.  Switch to the integration branch:
    ```bash
    git checkout feature/iap-workforce-auth
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

## 🚀 Step 3: Deploy to Google Cloud Platform (GCP)

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
4.  Follow the interactive prompts:
    *   **GCP Project ID**: Enter `[PROJECT_NAME]`.
    *   **Environment**: Select `development`.
    *   **Authentication Choice**: Select **(2) Microsoft Entra ID**.
    *   **Entra Client ID**: Paste the *Application (client) ID* collected in Step 2.
    *   **Entra Tenant ID**: Paste the *Directory (tenant) ID* collected in Step 2.
    *   **Entra Client Secret**: Paste the *Client Secret Value* collected in Step 2.
    *   **Domain Name**: Enter your domain (e.g., `[YOUR_DOMAIN_OR_IP]` or your custom domain).
    *   **GCP Organization ID**: Enter your GCP Organization numerical ID (required for Workforce Pools).

The script will automatically update the `infra/environments/development/development.tfvars` file, create the necessary secrets in GCP Secret Manager, and trigger the Terraform execution to deploy all resources (Cloud Run, Cloud SQL, IAP, GCS, etc.).

---

## 🌐 Step 4: Add a Custom Domain

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
