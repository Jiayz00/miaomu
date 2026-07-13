<?php
namespace app\plugins\nursery;

use app\plugins\nursery\service\CatalogMigration;

class Event
{
    public function Upload($params = [])
    {
        return DataReturn('success', 0);
    }

    public function BeginInstall($params = [])
    {
        return CatalogMigration::Preflight(isset($params['nursery_catalog_mode']) ? $params['nursery_catalog_mode'] : 'existing');
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
        return CatalogMigration::Preflight(isset($params['nursery_catalog_mode']) ? $params['nursery_catalog_mode'] : 'existing');
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
