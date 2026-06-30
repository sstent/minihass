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
        image = "ghcr.io/sstent/minihass:d801c3f2341e2e41adcbb78c4de85a93e1755bbd"
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