# Troubleshooting PDF Link Attachments

## Why PDF Links Might Not Appear

The PDF link attachment feature only appears when:

1. **Your query triggers paper search** - The system detects paper-related keywords
2. **OpenReview search finds papers** - Papers must be found in OpenReview with valid PDF links
3. **Backend returns PDF links** - The response must include the `pdf_links` array

## How to Test

### Step 1: Check Browser Console
1. Open browser DevTools (F12 or Cmd+Option+I)
2. Go to Console tab
3. Send a message asking about papers
4. Look for debug logs:
   - `✅ PDF links found:` - PDF links are present
   - `❌ No PDF links in response` - No PDF links found

### Step 2: Check Backend Logs
Look for these debug messages in the backend terminal:
- `DEBUG: Paper query detection - query: ...`
- `DEBUG: Searching OpenReview for: ...`
- `DEBUG: OpenReview search returned X results`
- `DEBUG: Extracted X PDF links`

### Step 3: Try These Queries
These queries should trigger paper search:
- "Find papers about transformers"
- "Search for ICLR papers on reinforcement learning"
- "Show me papers on neural architecture search"
- "Find papers by [author name]"
- "Search for papers about [topic]"

## Common Issues

### Issue 1: Query Not Detected
**Symptom**: No PDF links appear, no debug logs about paper query detection

**Solution**: Make sure your query contains paper-related keywords:
- "paper", "find", "search", "show me", "papers about", etc.

### Issue 2: OpenReview Search Returns No Results
**Symptom**: Debug shows "OpenReview search returned 0 results"

**Possible causes**:
- OpenReview credentials not configured
- Query too specific or no matching papers
- OpenReview API temporarily unavailable

**Solution**: 
- Check `.env` file has `OPENREVIEW_USERNAME` and `OPENREVIEW_PASSWORD`
- Try a more general query
- Check backend logs for OpenReview errors

### Issue 3: PDF Links Not Displayed
**Symptom**: Backend logs show PDF links extracted, but frontend doesn't show them

**Check**:
1. Browser console shows `✅ PDF links found`
2. Message object has `pdf_links` array
3. Frontend code is rendering (check React DevTools)

## Manual Testing

You can test the feature by asking:
```
"Find papers about transformer architecture"
```

This should:
1. Trigger OpenReview search
2. Find papers with PDF links
3. Display attachments below the assistant's response

## Debugging Steps

1. **Check Frontend Console**:
   ```javascript
   // In browser console, check the response
   // Look for: response.data.pdf_links
   ```

2. **Check Backend Logs**:
   ```bash
   # In backend terminal, look for DEBUG messages
   # Should see paper detection and PDF extraction logs
   ```

3. **Verify OpenReview Connection**:
   ```bash
   # Test OpenReview connection
   cd openreview_mcp
   python test_openreview_search.py
   ```

## Expected Behavior

When working correctly:
1. User asks: "Find papers about transformers"
2. Backend detects paper query
3. Backend searches OpenReview
4. Backend extracts PDF links
5. Backend returns response with `pdf_links` array
6. Frontend displays PDF attachments below message
7. User can click PDF button to open paper

## Still Not Working?

If PDF links still don't appear:
1. Check browser console for errors
2. Check backend terminal for errors
3. Verify OpenReview credentials are set
4. Try restarting both frontend and backend
5. Clear browser cache and reload

