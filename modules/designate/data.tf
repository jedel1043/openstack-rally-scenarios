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

data "external" "local_upstream_dns" {
  program = ["/bin/bash", "-c", <<EOF
      if command -v systemd-resolve > /dev/null; then
          servers=$(systemd-resolve --status 2> /dev/null | sed --regexp-extended 's/\s*DNS Servers:\s+([[:digit:]]+)/\1/g;t;d'| head -n 1)
      else
          servers=$(resolvectl 2> /dev/null | sed --regexp-extended 's/\s*Current DNS Server:\s+([[:digit:]]+)/\1/g;t;d')
      fi
      jq -Rsc '. / "\n" - [""] | tostring | {servers: .}' <<< $servers
    EOF
  ]
}