
resource "juju_application" "mysql" {
  name       = "mysql"
  model_uuid = juju_model.openstack.uuid
  charm {
    name    = "mysql-innodb-cluster"
    channel = "latest/edge"
    base    = "ubuntu@24.04"
  }
  units       = 3
  constraints = "mem=4G"
  config = {
    innodb-buffer-pool-size = "50%"
    max-connections         = 20000
    tuning-level            = "fast"
  }
}

resource "juju_application" "keystone" {
  name = "keystone"

  model_uuid = juju_model.openstack.uuid

  charm {
    name    = "keystone"
    channel = "latest/edge"
    base    = "ubuntu@24.04"
  }

  units = 3

  constraints = "mem=4G"

  config = {
    debug            = false
    verbose          = false
    openstack-origin = "distro"
  }
}

resource "juju_application" "glance" {
  name = "glance"

  model_uuid = juju_model.openstack.uuid

  charm {
    name    = "glance"
    channel = "latest/edge"
    base    = "ubuntu@24.04"
  }

  units = 3

  constraints = "mem=1G"

  config = {
    debug            = false
    verbose          = false
    openstack-origin = "distro"
  }
}

resource "juju_application" "ceph-mon" {
  name = "ceph-mon"

  model_uuid = juju_model.openstack.uuid

  charm {
    name    = "ceph-mon"
    channel = "squid/edge"
    base    = "ubuntu@24.04"
  }

  units = 1

  constraints = "mem=2G"

  config = {
    source             = "distro"
    loglevel           = 1
    monitor-count      = 1
    expected-osd-count = 3
  }
}

resource "juju_application" "ceph-osd" {
  name = "ceph-osd"

  model_uuid = juju_model.openstack.uuid

  charm {
    name    = "ceph-osd"
    channel = "squid/edge"
    base    = "ubuntu@24.04"
  }

  units = 3

  constraints = "mem=2G"

  config = {
    source      = "distro"
    loglevel    = 1
    osd-devices = ""
    config-flags = jsonencode({
      osd = {
        "osd memory target" = 1073741824
      }
    })
  }

  storage_directives = {
    osd-devices = "cinder,1,10G"
  }
}