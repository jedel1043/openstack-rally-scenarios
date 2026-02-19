terraform {
  required_providers {
    juju = {
      source  = "juju/juju"
      version = "1.1.0"
    }
  }
}

resource "juju_machine" "glance" {
  count       = 3
  model_uuid  = data.juju_model.openstack.uuid
  base        = "ubuntu@24.04"
  name        = "glance-m${count.index}"
  constraints = "mem=1G"

  placement = try(var.placement[count.index], null)

  // Ensures Terraform removes units first before destroying
  // machines, which avoids timeouts.
  lifecycle {
    create_before_destroy = true
  }
}

resource "juju_application" "glance" {
  name = "glance"

  model_uuid = data.juju_model.openstack.uuid

  charm {
    name    = "glance"
    channel = "latest/edge"
    base    = "ubuntu@24.04"
  }

  machines = toset(juju_machine.glance[*].machine_id)

  config = {
    debug            = false
    verbose          = false
    openstack-origin = "distro"
    vip              = var.vip
  }
}

resource "juju_application" "hacluster" {
  name = "glance-hacluster"

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
  name = "glance-mysql-router"

  model_uuid = data.juju_model.openstack.uuid

  charm {
    name    = "mysql-router"
    channel = "latest/edge"
    base    = "ubuntu@24.04"
  }
}
