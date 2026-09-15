# frozen_string_literal: true

require "test_helper"

class LocalNetworkTest < ActiveSupport::TestCase
  ROUTES = <<~TABLE
    Iface	Destination	Gateway 	Flags	RefCnt	Use	Metric	Mask		MTU	Window	IRTT
    eth0	00000000	010012AC	0003	0	0	0	00000000	0	0	0
    eth0	000012AC	00000000	0001	0	0	0	0000FFFF	0	0	0
  TABLE

  def route_table
    path = File.join(scratch_dir, "route")
    File.write(path, ROUTES)
    path
  end

  test "loopback addresses are local in every spelling" do
    %w[127.0.0.1 127.8.9.10 ::1 [::1] ::ffff:127.0.0.1].each do |addr|
      assert LocalNetwork.local_address?(addr, env: {}), addr
    end
    %w[10.0.0.1 192.168.1.1 172.18.0.1 ::ffff:10.0.0.1 garbage].each do |addr|
      refute LocalNetwork.local_address?(addr, env: {}), addr
    end
  end

  test "the docker default gateway is local only when trusted" do
    table = route_table
    assert_equal [IPAddr.new("172.18.0.1")], LocalNetwork.docker_gateways(table)
    refute LocalNetwork.local_address?("172.18.0.1", env: {}, route_table: table)
    assert LocalNetwork.local_address?("172.18.0.1", env: { "ZER0_CMS_TRUST_DOCKER_GATEWAY" => "1" }, route_table: table)
    refute LocalNetwork.local_address?("172.18.0.2", env: { "ZER0_CMS_TRUST_DOCKER_GATEWAY" => "1" }, route_table: table)
  end

  test "a missing route table trusts nothing" do
    assert_empty LocalNetwork.docker_gateways("/nonexistent/route")
  end
end
