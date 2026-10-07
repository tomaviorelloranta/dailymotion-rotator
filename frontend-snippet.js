<script>
(function () {
  // Replace OWNER, REPO, and BRANCH with the repository values.
  var redirectFile = "https://raw.githubusercontent.com/OWNER/REPO/BRANCH/redirect.txt";
  var cacheBustedUrl = redirectFile + "?v=" + Date.now();

  fetch(cacheBustedUrl, { cache: "no-store" })
    .then(function (response) {
      if (!response.ok) throw new Error("Redirect fetch failed");
      return response.text();
    })
    .then(function (text) {
      var url = text.trim();
      if (/^https:\/\/www\.dailymotion\.com\/video\/[A-Za-z0-9]+$/.test(url)) {
        window.location.replace(url);
      }
    })
    .catch(function (error) {
      console.error("Could not load the active video URL:", error);
    });
})();
</script>
