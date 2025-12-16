# openstack-rally-scenarios

This repository contains a list of [Rally](https://docs.openstack.org/rally/latest/)
scenarios to exercise an Openstack cluster. It also contains a set of Terraform
deployment files for every cluster configuration being tested.

# Requirements

- An active [Juju](https://canonical.com/juju) machine cloud.
- [Terraform](https://developer.hashicorp.com/terraform).
- [`uvx`] for easily running `Rally`

## Running a plan

Install Rally using `uv` for easier development.

```shell
uv tool install rally --with rally-openstack
```

Initialize Rally's database.

```shell
rally db create
```

Deploy a cluster to test a service.

```shell
terraform -chdir=deployments/<service> init
terraform -chdir=deployments/<service> apply
juju wait-for model openstack --timeout 20m --query='life=="alive" && status=="available" && forEach(applications, app => app.status == "active")'
```

Load the `OS_*` environment variables for this new cluster using the provided
`novarc` script and tell rally to use environment variables for authentication.

```shell
source novarc
rally deployment create --fromenv --name=openstack
```

Check that Rally can communicate with Openstack.

```shell
rally deployment check
```

Run a Rally task.

```shell
rally task start scenarios/<service>.json
```