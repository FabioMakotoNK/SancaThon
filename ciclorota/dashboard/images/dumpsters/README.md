# Real dumpster photographs

Add actual JPG/JPEG, PNG, WebP, AVIF, or GIF files here. There are currently no
identified dumpster photographs. Do not copy the unassigned webcam captures
from ciclorota/data into this public directory without identifying their source.

Link an image to a registered dumpster using image_url, for example:
/dashboard/images/dumpsters/your-photo.jpg

Use the dashboard photo-association form, POST /api/dumpsters at registration,
or PATCH /api/dumpsters/{id}/photo for an existing record. Null clears the link.
No upload endpoint exists. Rebuild Docker after adding photographs.
The generic placeholder in the parent directory is not a photograph.