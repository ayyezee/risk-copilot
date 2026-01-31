# Werdsmith

An AI-powered document processing platform for intelligent term replacement and document transformation. Built specifically for financial document workflows, particularly fund-of-funds (FoF) structures and Insurance Dedicated Funds (IDFs).

## Overview

Werdsmith analyzes documents, identifies terms requiring replacement based on reference examples, and generates transformed documents with AI-guided suggestions. It uses semantic search to find similar reference documents and leverages Claude's intelligence for context-aware replacements.

### Key Capabilities

- **Intelligent Term Replacement**: AI-driven identification and replacement of terms with context awareness
- **Fund-of-Funds Understanding**: Specialized logic for complex fund structures where the same term can have different meanings based on context
- **Reference-Based Learning**: Store before/after document pairs to build institutional knowledge
- **Formatting Preservation**: Maintain original DOCX formatting while applying replacements
- **Batch Processing**: Process multiple documents concurrently with real-time progress tracking
- **Grammar & Style Correction**: Automatic post-processing to fix grammar issues from replacements

## Tech Stack

### Backend
- **FastAPI** - Async Python web framework
- **PostgreSQL + pgvector** - Database with vector similarity search
- **SQLAlchemy** - Async ORM
- **Celery + Redis** - Background task processing
- **Claude (Anthropic)** - Primary AI for text analysis and generation
- **Voyage AI** - High-quality embeddings for semantic search

### Frontend
- **React 18** + TypeScript
- **Vite** - Build tool
- **TailwindCSS** + shadcn/ui - Styling and components
- **Zustand** - State management
- **React Query** - Server state

## Project Structure

```
werdsmith/
├── backend/
│   ├── app/
│   │   ├── api/routes/           # API endpoints
│   │   │   ├── auth.py           # Authentication & 2FA
│   │   │   ├── documents.py      # Document upload & management
│   │   │   ├── document_processing.py  # AI-powered processing
│   │   │   ├── reference_examples.py   # Reference library
│   │   │   ├── batch.py          # Batch processing with WebSocket
│   │   │   └── analytics.py      # Metrics dashboard
│   │   ├── services/             # Business logic
│   │   │   ├── ai_service.py     # AI provider abstraction
│   │   │   ├── document_ai_processor.py  # Term replacement analysis
│   │   │   ├── document_generator.py     # DOCX output with formatting
│   │   │   ├── pgvector_store.py # Vector database operations
│   │   │   ├── term_extractor.py # AI-driven term discovery
│   │   │   └── batch_processor.py # Concurrent batch processing
│   │   ├── models/               # Database models & schemas
│   │   ├── core/                 # Auth, security, exceptions
│   │   └── workers/              # Celery background tasks
│   ├── docker-compose.yml
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── pages/                # React pages
│   │   ├── components/           # Reusable UI components
│   │   ├── hooks/                # Custom React hooks
│   │   ├── services/             # API client
│   │   └── stores/               # Zustand state
│   └── package.json
└── README.md
```

## Core Services

### Document AI Processor
The heart of the system. Uses Claude's tool_use feature for structured output:
- Analyzes documents chunk by chunk
- Identifies terms requiring replacement
- Provides confidence scores and reasoning
- Handles context-sensitive terms (e.g., "Limited Partners" can refer to different entities)

### Document Generator
Applies replacements while preserving document formatting:
- Maintains DOCX run-level formatting (bold, italic, fonts)
- Highlights changes for review
- Deduplicates redundant phrases
- Fixes grammar issues (subject-verb agreement, possessives, pronouns)
- Generates changes report

### PGVector Store
Semantic search using PostgreSQL with pgvector:
- 1024-dimensional Voyage embeddings
- Finds similar reference documents
- Powers context-aware suggestions

### Term Extractor
Discovers defined terms in documents:
- Identifies capitalized terms
- Finds terms with formal definitions
- Extracts context sentences

## AI Integration

### Claude (Anthropic)
Primary AI provider for:
- Document analysis and term identification
- Context-aware replacement suggestions
- Structured output via tool_use
- Document summarization

### Voyage AI
Preferred embedding provider:
- `voyage-3` model (1024 dimensions)
- High-quality semantic similarity
- Used for reference document matching

### OpenAI (Fallback)
Alternative provider:
- GPT-4o for text generation
- text-embedding-3-small for embeddings

## Document Processing Pipeline

```
1. Upload Document (PDF, DOCX, TXT, Markdown)
           ↓
2. Extract Text & Metadata
           ↓
3. Semantic Search for Similar Reference Examples
           ↓
4. Claude Analyzes Document with Reference Context
           ↓
5. Generate Term Replacements with Confidence Scores
           ↓
6. User Reviews Suggestions
           ↓
7. Apply Replacements with Formatting Preservation
           ↓
8. Post-Process Grammar & Style Fixes
           ↓
9. Generate Output DOCX with Highlighted Changes
```

## Fund-of-Funds Intelligence

Werdsmith understands complex fund structures where the same term can have different meanings:

**Example: "Limited Partners"**
- When referring to IDF investors → Replace with "Series Limited Partners"
- When the IDF invests in portfolio funds → Replace with "the XYZ Series"

The system detects:
- **FUND_VEHICLE**: The series/fund being documented
- **INVESTOR**: Investors in the fund vehicle
- **UNDERLYING_FUND**: Portfolio funds the vehicle invests in
- **MANAGER**: General partner, investment manager, etc.

## Grammar & Style Processing

Automatic post-processing fixes common issues:

| Issue | Before | After |
|-------|--------|-------|
| Possessive | XYZ Series's | XYZ Series' |
| Subject-verb agreement | The Investment Subadvisor are | The Investment Subadvisor is |
| Pronoun agreement | their capital contributions | its capital contributions |
| Repeated words | Series Series Limited Partners | Series Limited Partners |
| Duplicate entities | Neither X nor X can | X can |
| Sentence capitalization | the XYZ Series may not | The XYZ Series may not |

## Quick Start

### Prerequisites
- Docker & Docker Compose
- Node.js 18+ (for frontend development)

### Environment Setup

Create `backend/.env`:
```env
# AI Services
ANTHROPIC_API_KEY=sk-ant-...
VOYAGE_API_KEY=pa-...

# Database
DATABASE_URL=postgresql+asyncpg://postgres:postgres@db:5432/docprocessor

# Redis
REDIS_URL=redis://redis:6379/0

# Security
SECRET_KEY=your-super-secret-key-change-in-production
```

### Run with Docker

```bash
cd backend
docker-compose up -d
```

Services:
- API: http://localhost:8000
- API Docs: http://localhost:8000/api/v1/docs
- Frontend: http://localhost:3000 (if running separately)

### Frontend Development

```bash
cd frontend
npm install
npm run dev
```

## API Endpoints

### Authentication
- `POST /api/v1/auth/register` - User registration
- `POST /api/v1/auth/login` - Login with email/password
- `POST /api/v1/auth/2fa/setup` - Setup two-factor authentication

### Documents
- `POST /api/v1/documents/upload` - Upload document
- `GET /api/v1/documents` - List documents
- `POST /api/v1/process/documents/{id}/analyze` - Analyze for replacements
- `POST /api/v1/process/apply-replacements` - Apply replacements

### Reference Library
- `POST /api/v1/reference-library/examples` - Add reference example
- `POST /api/v1/reference-library/examples/search` - Semantic search

### Batch Processing
- `POST /api/v1/batch/create` - Create batch job
- `WS /api/v1/batch/{id}/progress` - Real-time progress via WebSocket

### Analytics
- `GET /api/v1/analytics/dashboard` - Metrics and insights

## Security Features

- JWT-based authentication with refresh tokens
- Two-factor authentication (TOTP) with backup codes
- Password hashing with bcrypt
- User-scoped data isolation
- Rate limiting

## Development

### Backend
```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

### Database Migrations
```bash
alembic upgrade head
```

### Running Tests
```bash
pytest
```

## Architecture Decisions

1. **pgvector over Chroma**: PostgreSQL-native vector search for better reliability and no additional infrastructure

2. **Claude's tool_use**: Structured JSON output for predictable term replacement data

3. **Voyage embeddings**: Higher quality semantic similarity than OpenAI embeddings for document matching

4. **Run-level DOCX editing**: Preserves formatting by editing at the run level rather than paragraph level

5. **Post-processing pipeline**: Grammar fixes applied after all replacements to handle edge cases

## License

Proprietary - All rights reserved

## Contributing

Internal development only. Contact the team for access.
