# Creative Studio Infrastructure

This repository contains the Terraform configuration for deploying the Creative Studio application platform (frontend and backend) to Google Cloud.

## 🚀 Overview

This infrastructure is managed using a modular, environment-based approach with Terraform. The key principles are:
* **Don't Repeat Yourself (DRY):** All the logic for creating a service is defined once in a reusable **module**.
* **Strong Isolation:** Each environment (`dev`, `prod`, etc.) is managed in its own directory, with its own state file, to prevent accidental changes to production.

## 📁 Directory Structure

The project is organized into `modules` and `environments`.

```
infrastructure/
│
├── modules/                # Reusable "Blueprints"
│   ├── cloud-run-service/  # Defines how to build ONE service
│   └── platform/           # Defines the ENTIRE application platform
│
└── environments/
    ├── dev/                # Configuration for the 'dev' environment
    │   ├── main.tf         # Calls the platform module with dev values
    │   ├── backend.tf      # Defines where to store the dev state file
    │   └── dev.tfvars      # Contains all variables for dev
    │
    └── prod/               # Configuration for the 'prod' environment
        └── ...
```
* **`/modules`**: Contains reusable building blocks. The `platform` module is the main entry point, which in turn uses the `cloud-run-service` module.
* **`/environments`**: Contains a directory for each distinct deployment environment. These directories call the `platform` module with the correct set of variables.

---

## Deploy in 20min!!
Just run this script which has a step by step approach for you to deploy the infrastructure and start the app, just follow the instructions
```
curl https://raw.githubusercontent.com/GoogleCloudPlatform/gcc-creative-studio/refs/heads/main/bootstrap.sh | bash
```

For better guidance, [we recorded a video](./screenshots/how_to_deploy_creative_studio.mp4) to showcase how to deploy Creative Studio in a completely new and fresh GCP Account.

<video controls autoplay loop width="100%" style="max-width: 1200px;">
  <source src="./screenshots/how_to_deploy_creative_studio.mp4" type="video/mp4">
  Your browser does not support the video tag. You can <a href="./screenshots/how_to_deploy_creative_studio.mp4">download the video here</a>.
</video>

## System Architecture & Dependencies

For a detailed overview of the **System Architecture**, **Technology Stack**, and **Dependencies**, please refer to the [Root README](../README.md#system-architecture).



