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

data "juju_application" "rabbitmq" {
  name       = var.rabbitmq
  model_uuid = data.juju_model.openstack.uuid
}

data "juju_application" "memcached" {
  name       = var.memcached
  model_uuid = data.juju_model.openstack.uuid
}

data "juju_application" "glance" {
  name       = var.glance
  model_uuid = data.juju_model.openstack.uuid
}

data "juju_application" "placement" {
  name       = var.placement
  model_uuid = data.juju_model.openstack.uuid
}

data "juju_application" "cinder" {
  name       = var.cinder
  model_uuid = data.juju_model.openstack.uuid
}

data "juju_application" "cinder-ceph" {
  name       = var.cinder_ceph
  model_uuid = data.juju_model.openstack.uuid
}

data "juju_application" "ceph" {
  name       = var.ceph
  model_uuid = data.juju_model.openstack.uuid
}

data "juju_application" "neutron-api" {
  count      = var.neutron_api != null ? 1 : 0
  name       = var.neutron_api
  model_uuid = data.juju_model.openstack.uuid
}

data "juju_application" "ovn-central" {
  count      = var.ovn_central != null ? 1 : 0
  name       = var.ovn_central
  model_uuid = data.juju_model.openstack.uuid
}

data "juju_application" "certificates" {
  count      = var.certificates != null ? 1 : 0
  name       = var.certificates.name
  model_uuid = data.juju_model.openstack.uuid
}