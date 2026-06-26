<div align="center">
  <img src="./screenshots/horizontal-creative-studio-next.png" alt="Creative Studio Hero Image" width="600">
  <br>
  <br>
  <h1 align="center">Google Cloud Creative Studio Platform</h1>
  <p align="center"><b>The First Google Cloud Open Source, All-in-One Agentic Studio <br> for Building High-Fidelity Multimedia Content 🚀</b></p>

  <p align="center">
    <img src="https://img.shields.io/badge/angular-%23DD0031.svg?style=for-the-badge&logo=angular&logoColor=white">
    <img src="https://img.shields.io/badge/FastAPI-005571?style=for-the-badge&logo=fastapi">
    <img src="https://img.shields.io/badge/google%20gemini-8E75B2?style=for-the-badge&logo=google%20gemini&logoColor=white">
    <img src="https://img.shields.io/badge/GoogleCloud-%234285F4.svg?style=for-the-badge&logo=google-cloud&logoColor=white">
    <a href="https://github.com/pylint-dev/pylint"><img src="https://img.shields.io/badge/linting-pylint-yellowgreen?style=for-the-badge"></a>
    <a href="https://github.com/google/gts"><img src="https://img.shields.io/badge/code%20style-google-blueviolet.svg?style=for-the-badge"></a>
    <img src="https://img.shields.io/badge/tailwindcss-%2338B2AC.svg?style=for-the-badge&logo=tailwind-css&logoColor=white">
  </p>

</div>

---

Creative Studio is a comprehensive, all-in-one Generative AI platform designed as a deployable solution for your own Google Cloud project. It serves as a powerful reference implementation and creative suite, showcasing the full spectrum of Google's state-of-the-art generative AI models on Vertex AI.

Built for creators, marketers, and developers, this application provides a hands-on, interactive experience with cutting-edge multimodal capabilities.

> ###### _This is not an officially supported Google product. This project is not eligible for the [Google Open Source Software Vulnerability Rewards Program](https://bughunters.google.com/open-source-security)._

---

## ☁️ Google Cloud Next '26 & Izumi Integration

We are super excited to announce that we will be at **Google Cloud Next '26**! Our team will be attending and showcasing our deep integration with the **Izumi Agent**. 

Learn more about the multi-agent multimedia ecosystem at the [Izumi Agent Repository](https://github.com/GoogleCloudPlatform/genmedia-izumi-agent/tree/main).

---

## Core Features 🎨

Creative Studio goes beyond simple demos, implementing advanced, real-world features that developers can learn from and build upon:

**🎬 Advanced Video Generation (Veo):**

- Generate high-quality videos from text prompts.
- Utilize Image-to-Video (R2V) capabilities, allowing users to upload reference images.
- Differentiate between reference types, using images for ASSET consistency or STYLE transfer.

**🖼️ High-Fidelity Image Generation (Imagen):**

- Create stunning images from detailed text descriptions.
- Explore a wide range of creative styles, lighting, and composition controls.

**✍️ Gemini-Powered Prompt Engineering:**

- **Prompt Rewriting:** Automatically enhance and expand user prompts for superior generation results.
- **Multimodal Critic:** Use Gemini's multimodal understanding to evaluate and provide feedback on generated images.

**📄 Brand Guidelines Integration:**

- Upload PDF style guides that the backend processes to automatically infuse brand identity into generated content.
- Features a robust, scalable upload mechanism using GCS Signed URLs to bypass server timeouts and handle large files efficiently.

**👕 Virtual Try-On (VTO):**

- Includes functionality for seeding system-level assets like garments and models, laying the groundwork for virtual try-on applications.

## GenMedia Screenshots | Creative Studio

<p align="center">
  <img src="./screenshots/creative-studio-screenshots.gif" alt="Creative Studio Screenshots Walkthrough" width="800">
</p>


## Deploy in 20min!!

Just run this script which has a step by step approach for you to deploy the infrastructure and start the app, just follow the instructions

```
curl https://raw.githubusercontent.com/GoogleCloudPlatform/gcc-creative-studio/refs/heads/main/bootstrap.sh | bash
```

For better guidance, [we recorded a video](./screenshots/how_to_deploy_creative_studio.mp4) to showcase how to deploy Creative Studio in a completely new and fresh GCP Account.

### Redeploying

To redeploy the latest changes to Creative Studio, simply sync your forked repository with the `main` branch. You can do this by clicking the **"Sync with main"** button on GitHub or manually by running `git pull upstream main` in your local repository.

The Cloud Build triggers will automatically detect the new code changes and start the process to redeploy the application (taking approximately 5 minutes).

![](./screenshots/github-sync-with-main.png)

*💡 Tip: If your fork is behind the upstream repository, you will see a **"Sync fork"** or **"Update branch"** button in this section that allows you to pull latest changes automatically with one click.*

In case there are infrastructure changes (e.g., new cloud resources or configuration), you may need to redeploy Creative Studio by running Terraform manually. However, that is usually not the case, and if required, a note will be added to the version release documentation.

<video controls autoplay loop width="100%" style="max-width: 1200px;">
  <source src="./screenshots/how_to_deploy_creative_studio.mp4" type="video/mp4">
  Your browser does not support the video tag. You can <a href="./screenshots/how_to_deploy_creative_studio.mp4">download the video here</a>.
</video>

## System Architecture

![](./screenshots/creative-studio-architecture.png)

The backend follows a **Modular, Feature-Driven Architecture**, heavily inspired by the principles of Hexagonal Architecture (Ports & Adapters).

- **Structure:** Code is organized by feature domain (e.g., /images, /galleries, /users) rather than by technical layer (/controllers, /services).
- **Rationale:**
  - **Scalability:** This approach prevents individual directories from becoming unwieldy as the application grows.
  - **Maintainability:** All code related to a single feature is co-located, making it easier to understand, modify, and test.
  - **High Cohesion, Low Coupling:** Modules are self-contained and interact through well-defined interfaces (services and DTOs), making the system robust and flexible.

### Technology Stack

| Category           | Technology / Service                                     |
| :----------------- | :------------------------------------------------------- |
| **Frontend**       | Angular, TypeScript, Angular Material, Tailwind CSS      |
| **Backend**        | Python, FastAPI, Pydantic                                |
| **Database**       | Google Cloud SQL (PostgreSQL)                            |
| **Cloud Provider** | Google Cloud Platform (GCP)                              |
| **Deployment**     | Cloud Run (for backend), Firebase Hosting (for frontend) |
| **AI Models**      | Imagen, Veo, Gemini (via Vertex AI SDK)                  |

### Dependencies

Regarding the dependencies of the APIs and Services we’ll use (the Google APIs `‘xxxx.googleapis.com’` will be enabled by the script automatically):

- `Github Account` (You must have a Github Account to fork the repository)
- `Google Cloud Account` (A GCP Project)

---

- `aiplatform.googleapis.com` (Vertex AI)
- `artifactregistry.googleapis.com` (Artifact Registry)
- `cloudbuild.googleapis.com` (Cloud Build)
- `cloudfunctions.googleapis.com` (Cloud Functions)
- `compute.googleapis.com` (Compute Engine)
- `firebase.googleapis.com` (Firebase)
- `sqladmin.googleapis.com` (Cloud SQL)
- `iamcredentials.googleapis.com` (IAM Service API)
- `iap.googleapis.com` (Cloud Identity-Aware Proxy)
- `identitytoolkit.googleapis.com` (Identity Platform)
- `run.googleapis.com` (Cloud Run)
- `secretmanager.googleapis.com` (Secret Manager)
- `texttospeech.googleapis.com` (Text to Speech)

For the deployment you can use CloudShell which already has all of the necessary, but in case of deploying from a computer, the script will automatically check for the following command-line tools and attempt to install them if they are missing or outdated.

- `gcloud` (Google Cloud SDK)
- `git`
- `jq` (JSON processor)
- `firebase-tools` (Firebase CLI)
- `uv` (Python package installer)
- `terraform` (version 1.13.0 or newer)

## 🛡️ Quality Standards & CI/CD

To ensure the highest level of quality and security, we enforce strict style guidelines and automated checks both locally and in our CI/CD pipeline.

### 🎨 Code Style Guidelines
- **Python**: We adhere to the [Google Python Style Guide](https://google.github.io/styleguide/pyguide.html), using `pylint` and `black`.
- **TypeScript**: We follow the [Angular Coding Style Guide](https://angular.dev/style-guide) and [Google's TypeScript Style Guide](https://github.com/google/gts) using `gts`.
- **Commit Messages**: We suggest following [Angular's Commit Message Guidelines](https://github.com/angular/angular/blob/main/contributing-docs/commit-message-guidelines.md).

### 🌿 Branching Model
We follow the [Git Flow](https://nvie.com/posts/a-successful-git-branching-model/) branching model. Please create feature branches from `dev` and submit pull requests back to `dev`.

### ⚙️ Automated Checks (Pre-commit & GitHub Actions)

Every Pull Request to `develop`, `test`, or `main` branches undergoes automated checks via GitHub Actions, and you can also run them locally:

- **Local Pre-commit Hook**: Runs in a Docker container on every commit to check styling and licenses. See the [Development Guide](./DEVELOPMENT.md#5-code-quality--pre-commit-hooks) for setup instructions.
- **Backend Tests**: Minimum **80%** code coverage enforced by `pytest-cov`.
- **Backend Linting**: Minimum score of **9.0/10** enforced by `pylint`.
- **Frontend Linting**: Enforced by `gts` in CI.
- **AI-Powered Review**: Automated reviews powered by Gemini to catch issues early.

## 🛠️ Contributing

We welcome contributions to Creative Studio! Whether it's new templates, features, bug fixes, or documentation improvements, your help is valued.

### Prerequisites for Contributing

- A **GitHub Account**.
- **2-Factor Authentication (2FA)** enabled on your GitHub account.
- Familiarity with the "Getting Started" section to set up your development environment.

For more detailed contribution guidelines, please refer to the `CONTRIBUTING.md` file.

### Local Development

For a comprehensive, step-by-step guide on how to set up and run Creative Studio on your local machine using Docker Compose, please refer to the [Local Development Guide](./DEVELOPMENT.md).

## Feedback

- **Found an issue or have a suggestion?** Please [raise an issue](https://github.com/GoogleCloudPlatform/gcc-creative-studio/issues) on our GitHub repository.
- **Share your experience!** We'd love to hear about how you're using Creative Studio or any success stories. Feel free to reach out to us at genmedia-creativestudio@google.com or discuss in the GitHub discussions.

# Relevant Terms of Service

[Google Cloud Platform TOS](https://cloud.google.com/terms)

[Google Cloud Privacy Notice](https://cloud.google.com/terms/cloud-privacy-notice)

# Responsible Use

Building and deploying generative AI agents requires a commitment to responsible development practices. Creative Studio provides to you the tools to build agents, but you must also provide the commitment to ethical and fair use of these agents. We encourage you to:

- **Start with a Risk Assessment:** Before deploying your agent, identify potential risks related to bias, privacy, safety, and accuracy.
- **Implement Monitoring and Evaluation:** Continuously monitor your agent's performance and gather user feedback.
- **Iterate and Improve:** Use monitoring data and user feedback to identify areas for improvement and update your agent's prompts and configuration.
- **Stay Informed:** The field of AI ethics is constantly evolving. Stay up-to-date on best practices and emerging guidelines.
- **Document Your Process:** Maintain detailed records of your development process, including data sources, models, configurations, and mitigation strategies.

# Disclaimer

**This is not an officially supported Google product.**

Copyright 2025 Google LLC. All Rights Reserved.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
