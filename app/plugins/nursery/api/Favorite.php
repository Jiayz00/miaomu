<?php
namespace app\plugins\nursery\api;

use app\plugins\nursery\service\FavoriteService;

class Favorite
{
    private $user;

    public function __construct($params = [])
    {
        $this->user = isset($params['user']) && is_array($params['user']) ? $params['user'] : [];
    }

    public function Add($params = [])
    {
        return request()->isPost() ? FavoriteService::Add($this->user, $params) : DataReturn('收藏写操作仅接受 POST 请求', -1);
    }

    public function Cancel($params = [])
    {
        return request()->isPost() ? FavoriteService::Cancel($this->user, $params) : DataReturn('收藏写操作仅接受 POST 请求', -1);
    }

    public function Status($params = [])
    {
        return FavoriteService::Status($this->user, $params);
    }

    public function List($params = [])
    {
        return FavoriteService::Listing($this->user, $params);
    }
}
?>
