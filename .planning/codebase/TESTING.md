# Testing Strategy

## Current Testing Status

### Backend Testing
**Status**: ❌ **No automated tests implemented**

The backend currently has:
- No unit tests
- No integration tests
- No API endpoint tests
- No database migration tests

### Frontend Testing
**Status**: ❌ **No automated tests implemented**

The frontend currently has:
- No component tests
- No integration tests
- No E2E tests
- ESLint configured but no test framework

### Firmware Testing
**Status**: ❌ **Manual testing only**

ESP32 firmware is tested manually:
- Upload to device
- Monitor serial output
- Test WiFi connectivity
- Verify cloud uploads

## Manual Testing Approach

### Backend Manual Testing
1. **Local Development**
   ```bash
   # Start server
   uvicorn main:app --reload
   
   # Test endpoints with curl or Postman
   curl http://localhost:8000/api/info
   ```

2. **Database Testing**
   - Check SQLite database with DB Browser
   - Verify Azure SQL connection with Azure Data Studio
   - Manual schema migration testing

3. **AI Integration Testing**
   - Upload test audio files
   - Verify transcription accuracy
   - Check summary generation
   - Monitor API usage and costs

### Frontend Manual Testing
1. **Development Server**
   ```bash
   cd client
   npm run dev
   # Open http://localhost:5173
   ```

2. **UI Testing**
   - Navigate through all pages
   - Test file upload functionality
   - Verify meeting list display
   - Check audio playback
   - Test image gallery

3. **Responsive Testing**
   - Test on different screen sizes
   - Mobile device testing
   - Browser compatibility (Chrome, Firefox, Safari)

### Firmware Manual Testing
1. **Serial Monitor Testing**
   ```
   # Monitor ESP32 output
   - WiFi connection status
   - HTTP request/response codes
   - Audio streaming status
   - Error messages
   ```

2. **Network Testing**
   - Verify WiFi connectivity
   - Test HTTPS connection to Azure
   - Monitor upload success rates
   - Check chunked transfer encoding

3. **Hardware Testing**
   - Microphone audio quality
   - Camera image quality
   - Power consumption
   - Device stability over time

## Deployment Testing

### Docker Build Testing
```bash
# Build container locally
docker build -t stt-app .

# Run container
docker run -p 8000:8000 stt-app

# Test endpoints
curl http://localhost:8000/api/info
```

### Azure Deployment Testing
1. **Pre-deployment**
   - Verify environment variables
   - Check Azure SQL connection string
   - Validate API keys

2. **Post-deployment**
   - Test `/api/info` endpoint
   - Upload test audio file
   - Verify database writes
   - Check logs in Azure Portal

3. **Integration Testing**
   - Test ESP32 → Azure upload
   - Verify end-to-end flow
   - Check AI processing
   - Monitor performance

4. **Session Tracking Testing** ✅ NEW
   - Test active session detection
   - Verify image-to-session association
   - Test multiple concurrent sessions
   - Validate session end logic

### Session Tracking Test Scenarios

#### Test 1: Basic Session Isolation
```bash
# 1. Start mic recording (creates session A)
# 2. Upload image → should link to session A
# 3. Stop recording → session A marked inactive
# 4. Start new recording (creates session B)
# 5. Upload image → should link to session B (NOT A)
```

#### Test 2: MAC Address Matching
```bash
# 1. Start recording from Mic Device A (MAC: aa:bb:cc:dd:ee:ff)
# 2. Upload image from Camera 1 → links to Device A session
# 3. Start recording from Mic Device B (MAC: 11:22:33:44:55:66)
# 4. Upload image from Camera 1 → links to Device B session (most recent)
```

#### Test 3: Manual Session End
```bash
# Test the /api/meetings/{id}/end_session endpoint
curl -X POST https://stt-premium-app.purplebay-3e569791.centralindia.azurecontainerapps.io/api/meetings/{id}/end_session

# Verify session_active = false
curl https://stt-premium-app.purplebay-3e569791.centralindia.azurecontainerapps.io/api/meetings/{id}
```

#### Test 4: Database Persistence
```bash
# 1. Create meetings with Azure SQL
# 2. Restart container: az containerapp revision restart
# 3. Verify data still exists (not lost)
# 4. Check session_active and session_end_timestamp fields
```


## Recommended Testing Strategy

### Phase 1: Unit Tests (Backend)
**Priority**: High

```python
# Example test structure (not implemented)
# tests/test_ai_engine.py
def test_transcribe_audio():
    # Test Whisper API integration
    pass

def test_summarize_meeting():
    # Test Gemini API integration
    pass

# tests/test_models.py
def test_meeting_creation():
    # Test ORM model creation
    pass

# tests/test_endpoints.py
def test_upload_endpoint():
    # Test file upload
    pass
```

**Tools to add**:
- `pytest` - Testing framework
- `pytest-asyncio` - Async test support
- `httpx` - Async HTTP client for testing
- `pytest-cov` - Code coverage

### Phase 2: Integration Tests (Backend)
**Priority**: Medium

```python
# tests/integration/test_api.py
def test_full_upload_flow():
    # Upload → Process → Retrieve
    pass

def test_session_management():
    # Test active session tracking
    pass
```

### Phase 3: Frontend Tests
**Priority**: Medium

```javascript
// tests/Dashboard.test.jsx
describe('Dashboard', () => {
  it('renders meeting list', () => {
    // Test component rendering
  });
});
```

**Tools to add**:
- `vitest` - Vite-native testing framework
- `@testing-library/react` - Component testing
- `@testing-library/user-event` - User interaction testing

### Phase 4: E2E Tests
**Priority**: Low

```javascript
// e2e/upload-flow.spec.js
test('complete upload and transcription flow', async () => {
  // Test full user journey
});
```

**Tools to add**:
- `playwright` or `cypress` - E2E testing frameworks

## Test Data

### Sample Audio Files
- **Location**: Should create `tests/fixtures/audio/`
- **Formats**: WAV, MP3, M4A
- **Durations**: 5s, 30s, 2min samples
- **Content**: Known transcripts for validation

### Sample Images
- **Location**: Should create `tests/fixtures/images/`
- **Formats**: JPEG, PNG
- **Sizes**: Various resolutions

### Mock Data
```python
# tests/fixtures/mock_data.py
MOCK_MEETING = {
    "id": "test-123",
    "filename": "test.wav",
    "status": "completed",
    "transcription_text": "Test transcript",
    "summary": "Test summary"
}
```

## CI/CD Integration (Future)

### GitHub Actions Workflow
```yaml
# .github/workflows/test.yml
name: Tests
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Run backend tests
        run: pytest
      - name: Run frontend tests
        run: npm test
```

## Performance Testing

### Load Testing
- **Tool**: `locust` or `k6`
- **Scenarios**:
  - Concurrent uploads
  - API endpoint stress testing
  - Database query performance

### Audio Processing Benchmarks
- Transcription time vs file size
- Memory usage during processing
- Concurrent processing limits

## Security Testing

### API Security
- Authentication testing (if implemented)
- Input validation testing
- SQL injection prevention
- XSS prevention in frontend

### Firmware Security
- HTTPS certificate validation
- Secure credential storage
- OTA update security

## Monitoring and Logging

### Current Logging
- **Backend**: `print()` statements (should migrate to `logging`)
- **Frontend**: `console.log()` (should add error tracking)
- **Firmware**: Serial monitor output

### Recommended Improvements
- Structured logging with `logging` module
- Log aggregation (Azure Application Insights)
- Error tracking (Sentry)
- Performance monitoring (New Relic, DataDog)

## Testing Gaps

### Critical Gaps
1. ❌ No automated test coverage
2. ❌ No CI/CD pipeline
3. ❌ No integration tests
4. ❌ No performance benchmarks

### Medium Priority Gaps
1. ⚠️ Manual testing only
2. ⚠️ No test data fixtures
3. ⚠️ No error tracking
4. ⚠️ Limited logging

### Nice to Have
1. 📋 E2E tests
2. 📋 Load testing
3. 📋 Security audits
4. 📋 Accessibility testing
