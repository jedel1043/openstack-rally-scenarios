terraform {
  required_providers {
    juju = {
      source  = "juju/juju"
      version = "1.1.0"
    }
  }
}

provider "juju" {}

resource "juju_model" "openstack" {
  name = "openstack"

  cloud {
    name = "prodstack"
  }
}