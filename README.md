# Dailymotion video rotator

The workflow uploads the repository's `video.mp4`, publishes a Dailymotion
video, updates `redirect.txt`, `last_id.txt`, and `counter.txt`, then attempts
to remove the previously recorded video. Add `video.mp4` beside `rotatie.py`;
it is intentionally not included here.

## Configure GitHub

1. Put these files in the root of a GitHub repository and add the video file.
2. Add repository Actions secrets named `DM_API_KEY`, `DM_API_SECRET`,
   `DM_USERNAME`, and `DM_PASSWORD`.
3. Enable GitHub Actions and run **Rotate Dailymotion video** manually once.
4. Replace `OWNER`, `REPO`, and `BRANCH` in `frontend-snippet.js` with the raw
   GitHub URL details, then place the snippet in the Blogger template once.

The Python code uses conservative retries: OAuth, GET, and DELETE calls can be
retried; file upload and video creation are single-attempt POSTs to reduce
duplicate uploads/videos when the service accepts a request but the response
is lost. Deletion failure is logged while preserving the newly published
redirect and state.

## Dailymotion API compatibility

These requested endpoints and `grant_type=password` are the legacy Platform
API. Dailymotion's current migration documentation says password grant is not
supported by API v2; the newer private-key flow uses `client_credentials`,
`https://oauth2.dailymotion.com/v2/token`, and scope `video.manage`. Confirm
that your Dailymotion API key/account still supports the legacy flow before
enabling the schedule. The script follows the endpoints and environment
variable names specified for this project.
