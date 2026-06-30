job "minihass" {
  datacenters = ["dc1"]

  group "smart-home" {
    network {
      mode = "host"
      port "http" {
        to = 5000
      }
    }

    service {
      name = "minihass"
      port = "http"
      
      check {
        type     = "http"
        path     = "/health"
        interval = "30s"
        timeout  = "5s"
      }
    }

    task "app" {
      driver = "docker"

      config {
        image = "ghcr.io/sstent/minihass:650aad05c80d3a6c03a2c4851a18e245f2e69aef"
        ports = ["http"]
      }

      env {
        CONSUL_HOST = "consul.service.dc1.consul"
        CONSUL_PORT = "8500"
      }

      resources {
        cpu    = 500
        memory = 256
      }
    }
  }
}