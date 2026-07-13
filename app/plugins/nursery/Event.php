<?php
namespace app\plugins\nursery;

class Event
{
    public function Upload($params = [])
    {
        return DataReturn('success', 0);
    }

    public function BeginInstall($params = [])
    {
        return DataReturn('success', 0);
    }

    public function Install($params = [])
    {
        return DataReturn('success', 0);
    }

    public function Uninstall($params = [])
    {
        return DataReturn('success', 0);
    }

    public function Download($params = [])
    {
        return DataReturn('success', 0);
    }

    public function BeginUpgrade($params = [])
    {
        return DataReturn('success', 0);
    }

    public function Upgrade($params = [])
    {
        return DataReturn('success', 0);
    }

    public function Delete($params = [])
    {
        return DataReturn('success', 0);
    }
}
?>
