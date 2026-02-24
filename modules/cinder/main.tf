terraform {
  required_providers {
    juju = {
      source  = "juju/juju"
      version = "1.1.0"
    }
  }
}

resource "juju_machine" "cinder" {
  count       = 3
  model_uuid  = data.juju_model.openstack.uuid
  base        = "ubuntu@24.04"
  name        = "cinder-m${count.index}"
  constraints = "mem=1G"

  placement = try(var.unit_placement[count.index], null)

  // Ensures Terraform removes units first before destroying
  // machines, which avoids timeouts.
  lifecycle {
    create_before_destroy = true
  }
}

resource "juju_application" "cinder" {
  name = "cinder"

  model_uuid = data.juju_model.openstack.uuid

  charm {
    name    = "cinder"
    channel = "latest/edge"
    base    = "ubuntu@24.04"
  }

  machines = toset(juju_machine.cinder[*].machine_id)

  config = {
    debug              = false
    verbose            = false
    openstack-origin   = "distro"
    vip                = var.vip
    overwrite          = false
    glance-api-version = 2
  }
}

resource "juju_application" "hacluster" {
  name = "cinder-hacluster"

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
  name = "cinder-mysql-router"

  model_uuid = data.juju_model.openstack.uuid

  charm {
    name    = "mysql-router"
    channel = "latest/edge"
    base    = "ubuntu@24.04"
  }
}

resource "juju_application" "cinder-ceph" {
  name = "cinder-ceph"

  model_uuid = data.juju_model.openstack.uuid

  charm {
    name    = "cinder-ceph"
    channel = "latest/edge"
    base    = "ubuntu@24.04"
  }
}

output "cinder" {
  description = "Name of the Cinder application"
  value       = juju_application.cinder.name
}

output "cinder-ceph" {
  description = "Name of the Cinder Ceph application"
  value       = juju_application.cinder-ceph.name
}