# Privacy

This local profile reads only submitted paths under the workspace selected at
launch. Tool output is returned to the connected client and its chosen model.
No publisher service, telemetry endpoint, inference engine, or credential store
is used by this profile. Do not include confidential data in the selected
workspace unless that client and model are authorized to receive it.

## What it stores and sends

This profile stores nothing on disk. Network access is off unless the person who
installs the plugin names exact HTTPS origins at launch; then `gather.fetch` reads
those origins only, without credentials or redirects.

## Retention and support

Gather keeps no data after a call returns. Support and security reports:
https://github.com/HarperZ9/gather/issues
