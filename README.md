# ALAI - AI Chatbot

A full-stack AI chatbot application similar to ChatGPT, powered by Ollama with Qwen model.

## Features

- ChatGPT-like interface with dark theme
- Streaming AI responses
- Conversation history with sidebar navigation
- Microsoft OAuth login (optional)
- Anonymous user support with local storage
- Markdown and code syntax highlighting
- Responsive design

## Tech Stack

### Backend
- Python FastAPI
- PostgreSQL with SQLAlchemy ORM
- Alembic migrations
- JWT authentication
- Microsoft OAuth
- Ollama integration

### Frontend
- React 18 with TypeScript
- Vite
- TailwindCSS
- Zustand state management
- React Router

## Prerequisites

- Python 3.11+
- Node.js 20+
- PostgreSQL 15+
- Ollama with Qwen model installed

## Quick Start

### 1. Install Ollama and Qwen model

```bash
# Install Ollama from https://ollama.ai
# Pull the Qwen model
ollama pull qwen2.5
```

### 2. Setup Backend

```bash
cd backend

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Copy environment file
cp .env.example .env
# Edit .env with your settings

# Create database
createdb alai  # Or create via pgAdmin

# Run migrations
alembic upgrade head

# Start server
uvicorn app.main:app --reload --port 8000
```

### 3. Setup Frontend

```bash
cd frontend

# Install dependencies
npm install

# Start development server
npm run dev
```

### 4. Access the Application

Open http://localhost:3000 in your browser.

## Docker Setup

```bash
# Build and run with Docker Compose
docker-compose up --build

# The app will be available at http://localhost:3000
```

## Environment Variables

### Backend (.env)

```env
# Database
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/alai

# JWT
JWT_SECRET_KEY=your-secret-key

# Microsoft OAuth (optional)
MICROSOFT_CLIENT_ID=your-client-id
MICROSOFT_CLIENT_SECRET=your-client-secret
MICROSOFT_TENANT_ID=common
MICROSOFT_REDIRECT_URI=http://localhost:8000/api/auth/callback

# Ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5
```

### Frontend (.env)

```env
VITE_API_URL=http://localhost:8000
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/auth/login` | Get Microsoft OAuth URL |
| GET | `/api/auth/callback` | OAuth callback handler |
| GET | `/api/auth/me` | Get current user |
| POST | `/api/auth/logout` | Logout user |
| GET | `/api/conversations` | List conversations |
| POST | `/api/conversations` | Create conversation |
| GET | `/api/conversations/{id}` | Get conversation with messages |
| PATCH | `/api/conversations/{id}` | Rename conversation |
| DELETE | `/api/conversations/{id}` | Delete conversation |
| POST | `/api/conversations/{id}/messages/stream` | Send message & stream response |

## Project Structure

```
alai/
├── backend/
│   ├── app/
│   │   ├── ai/           # Ollama integration
│   │   ├── middleware/   # Auth middleware
│   │   ├── models/       # SQLAlchemy models
│   │   ├── repositories/ # Data access layer
│   │   ├── routers/      # API endpoints
│   │   ├── schemas/      # Pydantic schemas
│   │   ├── services/     # Business logic
│   │   ├── config.py     # Configuration
│   │   ├── database.py   # Database setup
│   │   └── main.py       # FastAPI app
│   ├── alembic/          # Migrations
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── components/   # React components
│   │   ├── hooks/        # Custom hooks
│   │   ├── layouts/      # Layout components
│   │   ├── pages/        # Page components
│   │   ├── services/     # API services
│   │   ├── store/        # Zustand stores
│   │   └── types/        # TypeScript types
│   └── package.json
└── docker-compose.yml
```

## Microsoft OAuth Setup

1. Go to [Azure Portal](https://portal.azure.com)
2. Navigate to Azure Active Directory > App registrations
3. Create a new registration
4. Add redirect URI: `http://localhost:8000/api/auth/callback`
5. Create a client secret
6. Copy Client ID and Secret to your `.env` file

## License

MIT
