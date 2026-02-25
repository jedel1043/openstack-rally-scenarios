terraform {
  required_providers {
    juju = {
      source  = "juju/juju"
      version = "1.1.0"
    }
  }
}

resource "juju_machine" "nova-cloud-controller" {
  count       = 3
  model_uuid  = data.juju_model.openstack.uuid
  base        = "ubuntu@24.04"
  name        = "nova-cloud-controller-m${count.index}"
  constraints = "mem=2G"

  placement = try(var.unit_placement[count.index], null)

  // Ensures Terraform removes units first before destroying
  // machines, which avoids timeouts.
  lifecycle {
    create_before_destroy = true
  }
}

resource "juju_application" "nova-cloud-controller" {
  name = "nova-cloud-controller"

  model_uuid = data.juju_model.openstack.uuid

  charm {
    name    = "nova-cloud-controller"
    channel = "latest/edge"
    base    = "ubuntu@24.04"
  }

  machines = toset(juju_machine.nova-cloud-controller[*].machine_id)

  config = {
    debug            = false
    verbose          = false
    openstack-origin = "distro"
    vip              = var.vip
    network-manager  = length(data.juju_application.neutron-api) > 0 ? "Neutron" : null
  }
}

resource "juju_application" "hacluster" {
  name = "nova-cloud-controller-hacluster"

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
  name = "nova-cloud-controller-mysql-router"

  model_uuid = data.juju_model.openstack.uuid

  charm {
    name    = "mysql-router"
    channel = "latest/edge"
    base    = "ubuntu@24.04"
  }
}

resource "juju_application" "nova-compute" {
  name = "nova-compute"

  model_uuid = data.juju_model.openstack.uuid

  charm {
    name    = "nova-compute"
    channel = "latest/edge"
    base    = "ubuntu@24.04"
  }

  units = 1

  constraints = "mem=8G cores=4"

  config = {
    debug                 = false
    verbose               = false
    openstack-origin      = "distro"
    enable-live-migration = true
    enable-resize         = true
    migration-auth-type   = "ssh"
    force-raw-images      = true
    libvirt-image-backend = "rbd"
  }

  # TODO: make this cloud generic
  storage_directives = {
    ephemeral-device = "cinder,50G,1"
  }
}

resource "juju_application" "ovn-chassis" {
  count = length(data.juju_application.ovn-central)
  name  = "ovn-chassis"

  model_uuid = data.juju_model.openstack.uuid

  charm {
    name    = "ovn-chassis"
    channel = "latest/edge"
    base    = "ubuntu@24.04"
  }

  config = {
    debug                = false
    ovn-bridge-mappings  = "physnet1:br-data"
    prefer-chassis-as-gw = true
  }
}
