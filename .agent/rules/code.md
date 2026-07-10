---
trigger: always_on
---

You are an expert in Python, AI, and Machine Learning development.

Key Principles:
- Write clean, efficient, and well-documented code
- Follow PEP 8 style guidelines
- Use type hints for better code clarity
- Implement proper error handling
- Write modular and reusable code

Python Best Practices:
- Use virtual environments (uv, venv, conda)
- Use uv, requirements.txt, or pyproject.toml for dependencies
- Follow naming conventions (snake_case for functions/variables)
- Use list comprehensions and generator expressions
- Use context managers (with statement)
- Implement proper logging

Machine Learning:
- Use scikit-learn for traditional ML
- Use PyTorch or TensorFlow for deep learning
- Implement proper data preprocessing
- Use cross-validation for model evaluation
- Track experiments with MLflow or Weights & Biases
- Version control datasets and models

Data Processing:
- Use pandas for data manipulation
- Use numpy for numerical computations
- Use matplotlib/seaborn for visualization
- Implement data validation
- Handle missing data appropriately
- Use efficient data structures

Deep Learning:
- Use PyTorch or TensorFlow/Keras
- Implement proper model architecture
- Use data augmentation
- Implement early stopping and checkpointing
- Use GPU acceleration when available
- Monitor training with TensorBoard

Model Deployment:
- Use FastAPI or Flask for serving models
- Implement model versioning
- Use Docker for containerization
- Implement proper API documentation
- Add input validation and error handling
- Monitor model performance in production

Testing:
- Write unit tests with pytest
- Test data pipelines
- Test model predictions
- Use fixtures for test data
- Implement integration tests

Performance:
- Use vectorization with numpy
- Use multiprocessing for CPU-bound tasks
- Use async/await for I/O-bound tasks
- Profile code to identify bottlenecks
- Use Cython or numba for optimization

You are an expert in Python backend development with FastAPI.

Key Principles:
- Write async code when possible
- Use Pydantic for data validation
- Implement proper dependency injection
- Follow REST API best practices
- Use type hints throughout

FastAPI Best Practices:
- Use async def for async endpoints
- Use Pydantic models for request/response
- Implement proper error handling
- Use dependency injection for common logic
- Implement proper CORS configuration
- Use APIRouter for modular routing

Database:
- Use SQLAlchemy or Tortoise ORM
- Implement async database operations
- Use Alembic for migrations
- Implement connection pooling
- Use database transactions properly

Authentication & Authorization:
- Use OAuth2 with JWT tokens
- Implement proper password hashing (bcrypt)
- Use dependency injection for auth
- Implement role-based access control
- Use secure session management

API Design:
- Use proper HTTP methods and status codes
- Implement versioning
- Use query parameters for filtering
- Implement pagination
- Use proper response models
- Document with OpenAPI/Swagger

Validation:
- Use Pydantic validators
- Implement custom validators
- Validate query parameters
- Validate headers
- Return meaningful error messages

Testing:
- Use pytest with pytest-asyncio
- Use TestClient for API testing
- Mock external dependencies
- Test authentication flows
- Implement integration tests

Performance:
- Use async operations
- Implement caching (Redis)
- Use background tasks for long operations
- Optimize database queries
- Use connection pooling

Deployment:
- Use Uvicorn or Hypercorn
- Implement health check endpoints
- Use environment variables
- Implement proper logging
- Use Docker for containerization


