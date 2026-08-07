"maintenance": true, "payg_price_per_second": "string" }

Refresh API token

# v0.0.1 OAS 3.1.0

## List available quantum computers

# Resonance integration API

## General

This API is meant to be consumed by customers that want to integrate to
Resonance programmatically. It provides stable, documented and backwards
compatible endpoints for all allowed Resonance operations. Higher level Python
libraries like iqm-qiskit or iqm-client use Resonance CoCoS API that is internal
[Image: Im29] [Image: Im30]
and subject to change without further notice, so integrating with it is not
recommended.

## Authentication

{ "quantum_computers": [ { "additional_info": { "academy_url":
"string", "best_suited_for": [ "string" ], "documentation_url":
"string", "mock_url": "string" }, "alias": "string",
"architecture": { "computational_components": [ { "name":
"string", "type": "qubit" } ], "connectivity": [ [ "QB1", "COMP_R"
] ], "name": "string", "operations": { "barrier": { "supported":
true }, "cc_prx": { "supported": true, "supported_qubits": [
"string" ] }, "cz": { "supported": true, "supported_loci": [ [
"QB1", "COMP_R" ] ], "symmetric": true }, "delay": { "supported":
true }, "measure": { "supported": true, "supported_qubits": [
"string" ] }, "move": { "supported": true, "supported_loci": [ [
"QB1", "COMP_R" ] ], "symmetric": true }, "prx": { "supported":
true, "supported_qubits": [ "string" ] }, "reset": { "supported":
true, "supported_qubits": [ "string" ] } } }, "backend_type":
"qpu", "cocos_endpoint": "string", "description": "string",

API endpoints support API token based authentication. To use this authentication
method, API users must provide a valid API token in the request's Authorization
[Image: Im31]
header as a bearer token, for example:

curl-X GET "https://api.resonance.meetiqm.com/quantum-computers/v1"
[Image: Im32]

User can obtain a valid API Token from the Resonance dashboard.

"maintenance": true, "payg_price_per_second": "string" } ] }

## API Tokens

Operations

POST /api-tokens/v1/activate

POST /api-tokens/v1/refresh

POST /api-tokens/v1/revoke

## Activate API token

Bodyrequired

application/json