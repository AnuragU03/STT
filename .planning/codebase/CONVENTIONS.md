# Coding Conventions

## Python Backend

### Code Style
- **PEP 8 compliance** - Standard Python style guide
- **Type hints** - Used in function signatures (`-> Dict[str, Any]`)
- **Async/await** - For I/O-bound operations (transcription)
- **Docstrings** - Triple-quoted strings for function documentation

### Naming Conventions
- **Files**: `snake_case.py` (e.g., `ai_engine.py`, `database.py`)
- **Classes**: `PascalCase` (e.g., `Meeting`, `MeetingImage`)
- **Functions**: `snake_case` (e.g., `get_meeting`, `process_meeting_task`)
- **Constants**: `UPPER_SNAKE_CASE` (e.g., `UPLOAD_DIR`, `SAMPLE_RATE`)
- **Private functions**: Prefix with `_` (not heavily used in this codebase)

### Database Conventions
- **Table names**: Lowercase plural (e.g., `meetings`, `meeting_images`)
- **Column names**: `snake_case` (e.g., `upload_timestamp`, `mac_address`)
- **Primary keys**: String UUIDs (e.g., `id = str(uuid.uuid4())`)
- **Indexes**: Descriptive names (e.g., `idx_active_sessions`)

### API Conventions
- **Endpoint paths**: `/api/resource` format
- **HTTP methods**: RESTful (GET, POST, DELETE, PATCH)
- **Response format**: JSON with consistent structure
  - Success: `{"status": "ok", ...}`
  - Error: `{"detail": "error message"}`
- **Status codes**: Standard HTTP (200, 404, 500)

### Error Handling
- **Try-except blocks** - Catch specific exceptions
- **Logging** - Print statements for debugging (should migrate to `logging` module)
- **Graceful degradation** - Fallback responses on AI failures
- **Database transactions** - Commit/rollback patterns

## Frontend (React)

### Code Style
- **ESLint** - JavaScript linting enabled
- **Functional components** - No class components
- **Hooks** - useState, useEffect for state management
- **JSX** - React component syntax

### Naming Conventions
- **Files**: `PascalCase.jsx` for components (e.g., `Dashboard.jsx`)
- **Components**: `PascalCase` (e.g., `MeetingDetail`)
- **Functions**: `camelCase` (e.g., `fetchMeetings`, `handleDelete`)
- **CSS classes**: `kebab-case` or Tailwind utilities

### Component Structure
```jsx
// Imports
import { useState, useEffect } from 'react';
import axios from 'axios';

// Component definition
function ComponentName() {
  // State declarations
  const [data, setData] = useState(null);
  
  // Effects
  useEffect(() => {
    // Side effects
  }, [dependencies]);
  
  // Event handlers
  const handleAction = () => {
    // Logic
  };
  
  // Render
  return (
    <div>
      {/* JSX */}
    </div>
  );
}

export default ComponentName;
```

### Styling Conventions
- **TailwindCSS** - Utility-first approach
- **Inline classes** - Applied directly to JSX elements
- **Responsive design** - Mobile-first with breakpoints
- **Custom CSS** - Minimal, in `index.css` for global styles

## ESP32 Firmware (C++)

### Code Style
- **Arduino conventions** - Standard Arduino framework patterns
- **Comments** - Section headers with `=====` separators
- **Constants** - `#define` for pins and configuration
- **Global variables** - Declared at file scope

### Naming Conventions
- **Files**: `snake_case.ino` (e.g., `esp32_mic_live.ino`)
- **Functions**: `camelCase` (e.g., `setupI2S`, `handleStart`)
- **Constants**: `UPPER_SNAKE_CASE` (e.g., `CLOUD_HOST`, `SAMPLE_RATE`)
- **Pin definitions**: `UPPER_SNAKE_CASE` with `_GPIO_NUM` suffix

### Configuration Pattern
```cpp
// ================= SECTION NAME =================
const char* config_var = "value";
#define PIN_NAME 25

// Function implementation
void functionName() {
  // Logic
}
```

### Hardware Conventions
- **I2S pins** - Defined as constants (WS, SD, SCK)
- **Camera pins** - AI-Thinker module standard pinout
- **WiFi credentials** - Hardcoded (should be moved to config)
- **Server URLs** - Hardcoded HTTPS endpoints

## General Conventions

### Version Control
- **Git** - Standard Git workflow
- **Commits** - Descriptive messages (not enforced)
- **Branches** - (Not observed in current structure)

### Environment Variables
- **Backend**: `.env` file for secrets (not committed)
  - `OPENAI_API_KEY`
  - `GOOGLE_API_KEY`
  - `AZURE_SQL_CONNECTION_STRING`
- **Frontend**: Vite environment variables (if needed)
- **Firmware**: Hardcoded (security concern)

### File Organization
- **Separation of concerns** - Each file has single responsibility
- **Modular structure** - Database, AI, models in separate files
- **No circular imports** - Clean dependency graph

### Documentation
- **README.md** - High-level project documentation
- **Inline comments** - Explain complex logic
- **Docstrings** - Function-level documentation
- **Type hints** - Self-documenting function signatures

## Areas for Improvement

### Backend
- Migrate from `print()` to `logging` module
- Add input validation with Pydantic models
- Implement proper exception classes
- Add API versioning (`/api/v1/...`)
- Use environment variables for all configuration

### Frontend
- Add PropTypes or TypeScript for type safety
- Implement error boundaries
- Add loading states and error handling
- Use environment variables for API URL
- Add unit tests

### Firmware
- Move WiFi credentials to separate config file
- Add OTA update support
- Implement retry logic for failed uploads
- Add status LED indicators
- Use SPIFFS for configuration storage

### General
- Add comprehensive test coverage
- Implement CI/CD pipeline
- Add API documentation (Swagger/OpenAPI)
- Implement proper logging and monitoring
- Add security headers and CORS configuration
