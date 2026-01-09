resource "juju_integration" "ceph-mon-to-ceph-osd" {
  model_uuid = juju_model.openstack.uuid
  application {
    name     = juju_application.ceph-mon.name
    endpoint = "osd"
  }

  application {
    name     = juju_application.ceph-osd.name
    endpoint = "mon"
  }
}

resource "juju_integration" "glance-to-ceph" {
  model_uuid = juju_model.openstack.uuid

  application {
    name     = juju_application.glance.name
    endpoint = "ceph"
  }

  application {
    name     = juju_application.ceph-mon.name
    endpoint = "client"
  }
}

resource "juju_integration" "glance-to-keystone" {
  model_uuid = juju_model.openstack.uuid

  application {
    name     = juju_application.glance.name
    endpoint = "identity-service"
  }

  application {
    name     = juju_application.keystone.name
    endpoint = "identity-service"
  }
}