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
        image = "ghcr.io/sstent/minihass:964fdb5c82c6c553420cf3a1463dc500751794c9"
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