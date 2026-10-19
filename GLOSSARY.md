# openFuyao on PolyMind

The vocabulary for the openFuyao quick-start capability inside PolyMind. It exists so product, frontend, backend, and agent prompts use one name for each thing.

## Language

**Environment**:
A single openFuyao management plane on one host, including its Bootstrap Cluster, Console, and owning Agent.
_Avoid_: Deployment, instance, platform

**Bootstrap**:
The act of preparing a host and initializing the Bootstrap Cluster that hosts Console.
_Avoid_: Install, setup, provision

**Bootstrap Cluster**:
The lightweight Kubernetes cluster created by Bootstrap; it hosts the openFuyao management components.
_Avoid_: Management cluster, control plane

**Console**:
The official openFuyao management UI for one Environment.
_Avoid_: Dashboard, panel, web UI

**Console Gateway**:
The boundary through which a browser reaches Console inside the PolyMind panel.
_Avoid_: Proxy, reverse proxy, iframe host

**Business Cluster**:
A Kubernetes cluster created from Console and managed by openFuyao.
_Avoid_: Workload cluster, target cluster, service cluster

**Node**:
A machine that participates in a Business Cluster as a master or worker.
_Avoid_: Host, server, machine

**Application**:
A Helm release installed from the openFuyao application market into a Business Cluster.
_Avoid_: App, service, workload

**Environment Owner**:
The single Agent that owns an Environment.
_Avoid_: Tenant, user, owner agent

**Quick Start**:
The three-stage openFuyao onboarding path: Bootstrap, create a Business Cluster, install an Application.
_Avoid_: Onboarding, tutorial, demo

**Manual Stage**:
A Quick Start stage performed by the user in Console rather than by an Agent.
_Avoid_: Human step, fallback, assisted mode

**AIO**:
All-in-one deployment where the Bootstrap Cluster and a Business Cluster share one host.
_Avoid_: Single-node, standalone, all-in-one cluster
