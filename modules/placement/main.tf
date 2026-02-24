terraform {
  required_providers {
    juju = {
      source  = "juju/juju"
      version = "1.1.0"
    }
  }
}

resource "juju_machine" "placement" {
  count       = 3
  model_uuid  = data.juju_model.openstack.uuid
  base        = "ubuntu@24.04"
  name        = "placement-m${count.index}"
  constraints = "mem=1G"

  placement = try(var.unit_placement[count.index], null)

  // Ensures Terraform removes units first before destroying
  // machines, which avoids timeouts.
  lifecycle {
    create_before_destroy = true
  }
}

resource "juju_application" "placement" {
  name = "placement"

  model_uuid = data.juju_model.openstack.uuid

  charm {
    name    = "placement"
    channel = "latest/edge"
    base    = "ubuntu@24.04"
  }

  machines = toset(juju_machine.placement[*].machine_id)

  config = {
    debug            = false
    openstack-origin = "distro"
    vip              = var.vip
  }
}

resource "juju_application" "hacluster" {
  name = "placement-hacluster"

  model_uuid = data.juju_model.openstack.uuid

  charm {
    name    = "hacluster"
    channel = "2.4/edge"
    base    = "ubuntu@24.04"
  }

  config = {
    cluster_count = 3
  }
}

resource "juju_application" "mysql-router" {
  name = "placement-mysql-router"

  model_uuid = data.juju_model.openstack.uuid

  charm {
    name    = "mysql-router"
    channel = "latest/edge"
    base    = "ubuntu@24.04"
  }
}

output "app_name" {
  description = "Name of the placement application"
  value       = juju_application.placement.name
}
