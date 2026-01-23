
(function() {
  const currentUrl = window.location.href;
  
  const url = new URL(currentUrl);
  const searchQuery = url.searchParams.get('q');
  
  let query = searchQuery || 
              url.searchParams.get('query') || 
              url.searchParams.get('search') ||
              url.searchParams.get('text');
  
  if (!query) {
    const searchParams = new URLSearchParams(window.location.search);
    query = searchParams.get('q') || searchParams.get('query') || searchParams.get('search');
  }
  
  if (query) {
    const alternativeEngine = 'https://duckduckgo.com/?q=' + encodeURIComponent(query);
    
    window.location.href = alternativeEngine;
  } else {
    alert('No search query found in URL. Make sure you are on a search results page.');
  }
})();

