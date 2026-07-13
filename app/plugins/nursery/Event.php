<?php
namespace app\plugins\nursery;

use app\plugins\nursery\service\CatalogMigration;
use app\plugins\nursery\service\FavoriteMigration;

class Event
{
    public function Upload($params = [])
    {
        return DataReturn('success', 0);
    }

    public function BeginInstall($params = [])
    {
        return $this->PreflightAll($params);
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
        return $this->PreflightAll($params);
    }

    public function Upgrade($params = [])
    {
        return DataReturn('success', 0);
    }

    public function Delete($params = [])
    {
        return DataReturn('success', 0);
    }

    private function PreflightAll($params)
    {
        $catalog = CatalogMigration::Preflight(isset($params['nursery_catalog_mode']) ? $params['nursery_catalog_mode'] : 'existing');
        if($catalog['code'] !== 0)
        {
            return $catalog;
        }
        $favorite = FavoriteMigration::Preflight();
        if($favorite['code'] !== 0)
        {
            return $favorite;
        }
        return DataReturn('苗木插件只读预检通过', 0, [
            'catalog'  => $catalog['data'],
            'favorite' => $favorite['data'],
        ]);
    }
}
?>
