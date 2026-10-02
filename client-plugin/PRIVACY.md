# Privacy

This local profile reads only submitted paths under the workspace selected at
launch. Tool output is returned to the connected client and its chosen model.
No publisher service, telemetry endpoint, inference engine, or credential store
is used by this profile. Do not include confidential data in the selected
workspace unless that client and model are authorized to receive it.

## What it stores and sends

This profile stores nothing on disk. Network access is off unless the person who
installs the plugin names exact origins at launch: public HTTPS origins in the
allowed public origins setting, or literal loopback origins such as
`http://127.0.0.1:8080` in the local service setting. Then `gather.fetch` sends GET
requests to those origins only, without credentials, cookies, custom headers or
redirects. The URL path and query chosen by the model reach that origin. The
hostnames of granted origins are looked up through the system DNS resolver. No
other destination is contacted.

## Retention and support

Gather keeps no data after a call returns. Support and security reports:
https://github.com/HarperZ9/gather/issues
