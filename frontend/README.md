# Creative Studio Frontend

## 🚀 Frontend Setup

To run the frontend locally using Docker Compose, you need to configure the environment file.

### 1. Configure `development.environment.ts`

Copy from `environments/environment.development.ts.example` and create a new file `environments/environment.development.ts`.
Add the following configuration (replace values with your specific configuration):

```typescript
export const environment = {
  // Project ID: creative-studio-deploy
  firebase: {
    apiKey: "your-api-key",
    authDomain: "creative-studio-deploy.firebaseapp.com",
    projectId: "creative-studio-deploy",
    storageBucket: "creative-studio-deploy.firebasestorage.app",
    messagingSenderId: "your-messaging-sender-id",
    appId: "your-app-id",
    measurementId: "G-XXXXXXXX"
  },
  production: false,
  isLocal: true,
  GOOGLE_CLIENT_ID: 'XXXX-XXXXXXXXXXX.apps.googleusercontent.com',
  backendURL: 'http://localhost:8080/api',

  // Common env vars
  EMAIL_REGEX: /^(([^<>()[\]\\.,;:\s@"]+(\.[^<>()[\]\\.,;:\s@"]+)*)|(".+"))@((\[\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\])|(([a-zA-Z\-0-9]+\.)+[a-zA-Z]{2,}))$/,
  ADMIN: 'admin',
};
```

### 2. Running the Application

We use Docker Compose to run the application locally. Please refer to the [Development Guide](../DEVELOPMENT.md) for detailed instructions on how to start the services.

If you want to start just the frontend you can run the following command:

```bash
docker compose up frontend
```

## Code Styling & Commit Guidelines

To maintain code quality and consistency:

* **TypeScript (Frontend):** We follow [Angular Coding Style Guide](https://angular.dev/style-guide) by leveraging the use of [Google's TypeScript Style Guide](https://github.com/google/gts) using `gts`. This includes a formatter, linter, and automatic code fixer.
* **Commit Messages:** We suggest following [Angular's Commit Message Guidelines](https://github.com/angular/angular/blob/main/contributing-docs/commit-message-guidelines.md) to create clear and descriptive commit messages.

### Frontend (TypeScript with `gts`)

(Assumes setup within the `frontend/` directory)

1.  **Initialize `gts` (if not already done in the project):**
    Navigate to `frontend/` and run:
    ```bash
    npx gts init
    ```
    This will set up `gts` and create necessary configuration files (like `tsconfig.json`). Ensure your `tsconfig.json` (or a related `gts` config file like `.gtsrc`) includes an extension for `gts` defaults, typically:
    ```json
    {
      "extends": "./node_modules/gts/tsconfig-google.json"
      // ... other configurations
    }
    ```
2.  **Check for linting issues:**
    (This assumes a `lint` script is defined in `frontend/package.json`, e.g., `"lint": "gts lint"`)
    ```bash
    # from frontend/ directory
    npm run lint
    ```
3.  **Fix linting issues automatically (where possible):**
    (This assumes a `fix` script is defined in `frontend/package.json`, e.g., `"fix": "gts fix"`)
    ```bash
    # from frontend/ directory
    npm run fix
    ```

