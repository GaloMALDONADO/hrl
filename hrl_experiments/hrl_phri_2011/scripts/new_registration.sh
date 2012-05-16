#!/bin/bash 
pkg=`rospack find hrl_phri_2011`
source $pkg/scripts/variables.sh
set -x
rosrun hrl_phri_2011 pub_head $dir/sub1_head_stitched.bag /stitched_head /base_link 1 &
rosrun hrl_phri_2011 interactive_tf base_link /contact_cloud 20 $dir/${people[$1]}_${tools[$2]}_${places[$3]}_contact_registration_new.bag &
rosrun hrl_phri_2011 pub_head $dir/${people[$1]}_${tools[$2]}_${places[$3]}_contact_cloud_colored.bag /contact_cloud /contact_cloud 20
