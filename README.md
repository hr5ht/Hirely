# MockHire

MockHire is an intelligent interview preparation platform designed to help candidates practice and improve their interviewing skills through advanced AI technology. It combines ATS resume scanning, dynamic mock interview sessions, and comprehensive dashboard analytics into a single cohesive experience.

This application allows candidates to upload their resumes to be scanned, simulate real-world interview conditions, and receive actionable feedback on their performance. Simultaneously, it offers a beautifully designed, minimalist dashboard to track past interviews and manage session data effortlessly.

## Features

### For Candidates

- **Intelligent ATS Resume Scanner**: Built-in resume evaluation directly to analyze uploaded resumes and ensure they meet industry standards.
- **AI-Powered Mock Interviews**: Real-time simulated conversational interviews powered by the Groq SDK and advanced language models to provide accurate, constructive feedback.
- **Modern Interactive UI**: A clean, minimalist light-themed interface designed for an excellent, stress-free user experience during the interview process.
- **Session Dashboard**: A centralized hub to display recent interview activity, track overall progress, and review detailed feedback from past sessions.

## Technology Stack

### Frontend

- **HTML/CSS & JavaScript**: Core technologies for a modern, responsive minimalist user interface.
- **Dynamic UI Components**: Leveraging tailored, responsive designs for the landing, login, registration, and session pages.

### Backend

- **Django & ASGI**: High-level Python web framework providing robust backend logic via asynchronous capabilities, handling authentication, interview session state, and routing.
- **Uvicorn**: Lightning-fast ASGI server used to run the Django application.
- **Groq SDK**: Integrated high-speed inference engine powering the AI conversational Mock Interview logic.
- **SQLite**: Lightweight database for local development and managing user profiles and session history.

## Getting Started

Follow these instructions to set up the project locally on your machine.

### Prerequisites

- Python (v3.10 or higher)
- Git

### Installation

1.  **Clone the repository**

    ```bash
    git clone <repository-url>
    cd MockHire
    ```

2.  **Environment Setup**
    Navigate to the backend directory and set up the Python environment.

    ```bash
    cd backend
    python -m venv venv
    source venv/bin/activate  # On Windows use `venv\Scripts\activate`
    pip install -r requirements.txt
    ```

    Ensure your environment variables are set up (e.g., API keys for Groq).

    ```bash
    # Create or update your .env file
    cp .env.example .env
    ```

3.  **Database Configuration**
    Run the database migrations:

    ```bash
    python manage.py migrate
    ```

4.  **Start the Server**
    Start the application using Uvicorn through Django's ASGI configuration:
    ```bash
    uvicorn backend.asgi:application --reload
    ```
    The platform will be accessible at `http://127.0.0.1:8000`.

## Usage

1.  Ensure the Uvicorn server is running.
2.  Open your browser and navigate to the application URL (e.g., `http://127.0.0.1:8000`).
3.  **Register/Login**: Create a new account or log in through the minimalist portal.
4.  **Resume Upload**: Navigate to the upload section to have your resume scanned and evaluated by the built-in ATS system.
5.  **Mock Interviews**: Start a dynamic session, interact with the AI interviewer, and review your performance via the dashboard.

## License

This project is licensed under the MIT License.
