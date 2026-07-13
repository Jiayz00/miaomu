<?php
namespace app\plugins\nursery\index;

use app\plugins\nursery\service\FavoriteService;

class Favorite
{
    private $user;

    public function __construct($params = [])
    {
        $this->user = isset($params['user']) && is_array($params['user']) ? $params['user'] : [];
    }

    public function Index($params = [])
    {
        IsUserLogin();
        $result = FavoriteService::Listing($this->user, $params);
        if($result['code'] !== 0)
        {
            return MyView('public/tips_error', ['msg'=>$result['msg']]);
        }
        MyViewAssign([
            'favorite_data' => $result['data'],
            'csrf_token'    => FavoriteService::WebCsrfToken(),
        ]);
        return MyView('../../../plugins/nursery/view/index/favorite/index');
    }

    public function Add($params = [])
    {
        IsUserLogin();
        $guard = FavoriteService::ValidateWebWrite($params);
        return ($guard['code'] === 0) ? FavoriteService::Add($this->user, $params) : $guard;
    }

    public function Cancel($params = [])
    {
        IsUserLogin();
        $guard = FavoriteService::ValidateWebWrite($params);
        return ($guard['code'] === 0) ? FavoriteService::Cancel($this->user, $params) : $guard;
    }

    public function Status($params = [])
    {
        IsUserLogin();
        return FavoriteService::Status($this->user, $params);
    }

    public function List($params = [])
    {
        IsUserLogin();
        return FavoriteService::Listing($this->user, $params);
    }
}
?>
