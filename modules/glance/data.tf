data "juju_model" "openstack" {
  uuid = var.model_uuid
}

data "juju_application" "keystone" {
  name       = var.keystone
  model_uuid = data.juju_model.openstack.uuid
}

data "juju_application" "mysql" {
  name       = var.mysql
  model_uuid = data.juju_model.openstack.uuid
}

data "juju_application" "ceph" {
  name       = var.ceph
  model_uuid = data.juju_model.openstack.uuid
}
